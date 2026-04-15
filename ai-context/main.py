from astrbot.api.event import filter, AstrMessageEvent, MessageEventResult
from astrbot.api.star import Context, Star, register
from astrbot.api import logger, llm_tool
from astrbot.core.agent.message import TextPart
from astrbot.core.provider.entities import ProviderRequest
from astrbot.core.provider import Provider
from astrbot.core.utils.astrbot_path import get_astrbot_data_path
import datetime
import zoneinfo
import os
from pathlib import Path
from datetime import datetime, timedelta
import re
from zoneinfo import ZoneInfo
from typing import Optional

@register("astrbot-memory-plugin", "ssslock", "自用记忆管理插件", "0.2.0")
class MyPlugin(Star):
    def __init__(self, context: Context):
        super().__init__(context)
        # Always convert to Path object to ensure proper path joining
        data_path = get_astrbot_data_path()
        # Convert to string first, then to Path
        data_path = Path(str(data_path))
        # Handle self.name which may not be available in older versions
        plugin_name = getattr(self, 'name', 'astrbot-memory-plugin')
        self.plugin_id = plugin_name  # Required for PluginKVStoreMixin
        self.plugin_data_path = data_path / "plugin_data" / plugin_name
        self.memory_path = self.plugin_data_path / "memory"
        self.self_prompt_path = self.memory_path / "self_prompt"
        self.ttl_cron_job_id = None  # Add this to track cron job

    def _parse_ttl(self, ttl_str: str) -> Optional[timedelta]:
        """Parse TTL string like '5h', '20d', '6m', '1y' into timedelta."""
        if ttl_str.lower() == "permanent":
            return None
        
        # Strict validation
        if len(ttl_str) >= 5:  # length must be smaller than 5
            return None
        
        if not ttl_str.endswith(('h', 'd', 'm', 'y')):
            return None
        
        # Check all other characters are digits
        prefix = ttl_str[:-1]
        if not prefix.isdigit():
            return None
        
        # Parse the number
        try:
            num = int(prefix)
            if num < 0:
                return None
        except ValueError:
            return None
        
        # Convert to timedelta
        unit = ttl_str[-1]
        if unit == 'h':
            return timedelta(hours=num)
        elif unit == 'd':
            return timedelta(days=num)
        elif unit == 'm':
            return timedelta(days=num * 30)  # Approximate month as 30 days
        elif unit == 'y':
            return timedelta(days=num * 365)  # Approximate year as 365 days
        else:
            return None

    def _get_ttl_date_key(self, date: datetime) -> str:
        """Generate key for TTL date to files mapping (hour-based)."""
        date_str = date.strftime("%Y-%m-%d %H:00")
        return f"TTL_DATE_TO_FILES:{date_str}"

    def _get_file_ttl_key(self, relative_path: str) -> str:
        """Generate key for file to TTL date mapping."""
        return f"TTL_FILE_TO_DATE:{relative_path}"

    async def _setup_ttl(self, relative_path: str, ttl_str: str) -> str:
        """Setup TTL for a file."""
        ttl_delta = self._parse_ttl(ttl_str)
        if ttl_delta is None:
            return "No TTL setup (invalid format or permanent)"
        
        # Calculate expiration date (adding current datetime + ttl_delta)
        now = datetime.now()
        expire_date = now + ttl_delta + timedelta(hours=1)  # Add 1 hour buffer to ensure it doesn't expire immediately
        
        # Round down to the current hour
        expire_date = expire_date.replace(minute=0, second=0, microsecond=0)
        
        # Store file->date mapping
        expire_date_str = expire_date.strftime("%Y-%m-%d %H:00")
        await self.put_kv_data(self._get_file_ttl_key(relative_path), expire_date_str)
        
        # Store date->files mapping
        date_key = self._get_ttl_date_key(expire_date)
        existing_files = await self.get_kv_data(date_key, "")
        if existing_files:
            new_files = existing_files + "\n" + relative_path
        else:
            new_files = relative_path
        
        await self.put_kv_data(date_key, new_files)
        
        return f"TTL set until {expire_date_str}"

    async def _delete_ttl(self, relative_path: str) -> None:
        """Delete TTL records for a file."""
        # Get the expiration date
        date_key = self._get_file_ttl_key(relative_path)
        expire_date_str = await self.get_kv_data(date_key, None)
        
        if not expire_date_str:
            return
        
        # Remove from date->files mapping
        files_key = f"TTL_DATE_TO_FILES:{expire_date_str}"
        files_str = await self.get_kv_data(files_key, "")
        
        if files_str:
            # Split by newline and filter out the current file
            files_list = files_str.split("\n")
            files_list = [f for f in files_list if f != relative_path]
            
            if files_list:
                await self.put_kv_data(files_key, "\n".join(files_list))
            else:
                await self.delete_kv_data(files_key)
        
        # Remove file->date mapping
        await self.delete_kv_data(date_key)

    async def _cleanup_expired_files(self) -> None:
        """Clean up files that have expired (cron job handler)."""
        now = datetime.now()
        
        # Check current hour and previous hour (to catch any missed files)
        hours_to_check = []
        for hours_back in [0, 1]:
            check_hour = now - timedelta(hours=hours_back)
            check_hour = check_hour.replace(minute=0, second=0, microsecond=0)
            hours_to_check.append(check_hour.strftime("%Y-%m-%d %H:00"))
        
        for hour_str in hours_to_check:
            files_key = f"TTL_DATE_TO_FILES:{hour_str}"
            files_str = await self.get_kv_data(files_key, "")
            
            if files_str:
                files_list = files_str.strip().split("\n")
                for relative_path in files_list:
                    if not relative_path.strip():
                        continue
                        
                    try:
                        # Remove the file
                        full_path = (self.memory_path / relative_path).resolve()
                        if full_path.exists() and full_path.is_file():
                            full_path.unlink()
                            logger.info(f"Removed expired file: {full_path}")
                        
                        # Clean up TTL records
                        await self._delete_ttl(relative_path)
                        
                    except Exception as e:
                        logger.error(f"Error cleaning up expired file {relative_path}: {e}")

    async def initialize(self):
        """可选择实现异步的插件初始化方法，当实例化该插件类之后会自动调用该方法。"""
        # Ensure the plugin data directory exists
        self.plugin_data_path.mkdir(parents=True, exist_ok=True)
        # Create subdirectories using instance variables
        self.memory_path.mkdir(parents=True, exist_ok=True)
        self.self_prompt_path.mkdir(parents=True, exist_ok=True)
        logger.info(f"Plugin data path: {self.plugin_data_path}")

        # Add TTL cleanup cron job
        try:
            job = await self.context.cron_manager.add_basic_job(
                name=f"{self.plugin_id}-ttl-cleanup",
                cron_expression="0 * * * *",  # Run at the start of every hour
                handler=self._cleanup_expired_files,
                description="Clean up expired memory files (hourly)",
                timezone=None,  # Use local timezone
                payload={},
                enabled=True,
                persistent=False,
            )
            self.ttl_cron_job_id = job.job_id
            logger.info(f"TTL cleanup cron job scheduled: {self.ttl_cron_job_id}")
        except Exception as e:
            logger.error(f"Failed to schedule TTL cleanup cron job: {e}")

    async def terminate(self):
        """可选择实现异步的插件销毁方法，当插件被卸载/停用时会调用。"""
        # Remove TTL cleanup cron job
        if self.ttl_cron_job_id:
            try:
                await self.context.cron_manager.delete_job(self.ttl_cron_job_id)
                logger.info(f"Removed TTL cleanup cron job: {self.ttl_cron_job_id}")
            except Exception as e:
                logger.error(f"Failed to remove TTL cleanup cron job: {e}")

    @filter.on_llm_request()
    async def on_llm_request(self, event: AstrMessageEvent, req: ProviderRequest):
        """Event handler for LLM requests to append self instructions from bot's self prompt file."""
        try:
            # Get self prompt file path using the helper
            relative_path = self._get_self_prompt_file_path(event)
            if relative_path is None:
                logger.warning("Could not get self prompt file path: self_id not found")
                return
            
            full_path = (self.self_prompt_path / relative_path).resolve()
            
            # Ensure the full path is within plugin_data_path (security check)
            if not str(full_path).startswith(str(self.plugin_data_path.resolve())):
                logger.error(f"Invalid self prompt path - outside plugin data directory: {full_path}")
                return
            
            # Create parent directories if they don't exist (should already exist from initialize)
            full_path.parent.mkdir(parents=True, exist_ok=True)
            
            # Try to read the file
            if os.path.exists(full_path):
                with open(full_path, 'r', encoding='utf-8') as f:
                    content = f.read().strip()
                if content:
                    # Append to system prompt
                    if req.system_prompt is None:
                        req.system_prompt = ""
                    req.system_prompt += f"\n# Self Instructions\n\n{content}\n"
                    logger.info(f"Appended self instructions from {full_path}")
            else:
                logger.debug(f"Self prompt file {full_path} does not exist, skipping")
                
        except Exception as e:
            logger.error(f"Error in on_llm_request handler for self prompt: {e}")

    @llm_tool(name="store_memory")
    async def store_memory(self, event: AstrMessageEvent, relative_path: str, content: str, ttl: str = "permanent") -> str:
        """Store memory content with a relative file path
        
        Args:
            relative_path (string): The relative file path where the content should be stored.
            content (string): The file content to store.
            ttl (string): Time to live in format like "5h", "20d", "6m", "1y". 
                          Must be shorter than 5 chars, end with h/d/m/y, and contain only digits before suffix.
                          "1h" = 1 hour, "1d" = 24 hours, "1m" = 30 days, "1y" = 365 days.
                          Use "permanent" for no expiration.
                          Cleanup runs at the start of each hour.
        
        Returns:
            string: "OK" if successful, otherwise an error message.
        """
        try:
            # Ensure the relative path is safe
            full_path = (self.memory_path / relative_path).resolve()
            # Ensure the full path is within plugin_data_path
            if not str(full_path).startswith(str(self.memory_path.resolve())):
                return "Error: Invalid path - cannot access outside memory directory"
            
            # Create parent directories if they don't exist
            full_path.parent.mkdir(parents=True, exist_ok=True)
            
            # Clear any existing TTL for this file
            await self._delete_ttl(relative_path)
            
            # Write the content
            full_path.write_text(content, encoding='utf-8')
            
            # Setup TTL if specified and valid
            ttl_result = ""
            if ttl.lower() != "permanent":
                ttl_result = await self._setup_ttl(relative_path, ttl)
            
            # Log for debugging
            logger.info(f"Stored file: {full_path}, content length: {len(content)}, ttl: {ttl}")
            
            if ttl_result and not ttl_result.startswith("No TTL setup"):
                return f"OK. {ttl_result}"
            return "OK"
        except Exception as e:
            logger.error(f"Error storing file: {e}")
            return f"Error: {str(e)}"

    @llm_tool(name="retrieve_memory")
    async def retrieve_memory(self, event: AstrMessageEvent, relative_path: str) -> str:
        """Retrieve stored memory content with a relative file path
        
        Args:
            relative_path (string): The relative file path to retrieve.
            
        Returns:
            string: The stored file name and content if found, or "not found" if it does not exist.
        """
        try:
            full_path = (self.memory_path / relative_path).resolve()
            # Ensure the full path is within plugin_data_path
            if not str(full_path).startswith(str(self.memory_path.resolve())):
                return "Error: Invalid path - cannot access outside memory directory"
            
            if full_path.exists() and full_path.is_file():
                content = full_path.read_text(encoding='utf-8')
                logger.info(f"Retrieved file: {full_path}, content length: {len(content)}")
                return f"File: {relative_path}, Content: {content}"
            else:
                logger.info(f"File not found: {full_path}")
                return "not found"
        except Exception as e:
            logger.error(f"Error retrieving file: {e}")
            return f"Error: {str(e)}"

    @llm_tool(name="remove_memory")
    async def remove_memory(self, event: AstrMessageEvent, relative_path: str) -> str:
        """Remove memory content with a relative file path
        
        Args:
            relative_path (string): The relative file path to delete.
            
        Returns:
            string: "deleted" if successfully deleted, "not found" if file doesn't exist, or an error message.
        """
        try:
            full_path = (self.memory_path / relative_path).resolve()
            # Ensure the full path is within plugin_data_path
            if not str(full_path).startswith(str(self.memory_path.resolve())):
                return "Error: Invalid path - cannot access outside memory directory"
            
            if full_path.exists() and full_path.is_file():
                # Remove TTL records first
                await self._delete_ttl(relative_path)
                
                # Then delete the file
                full_path.unlink()
                logger.info(f"Deleted file: {full_path}")
                return "deleted"
            else:
                logger.info(f"File not found for deletion: {full_path}")
                return "not found"
        except Exception as e:
            logger.error(f"Error deleting file: {e}")
            return f"Error: {str(e)}"

    @llm_tool(name="list_memory")
    async def list_memory(self, event: AstrMessageEvent, relative_path: str = ".") -> str:
        """List stored memory entries in a directory with a relative path
        
        Args:
            relative_path (string): The relative directory path to list. Defaults to current directory.
            
        Returns:
            string: A formatted list of entries with type (file/folder) and file size for files.
                    Returns "not found" if the directory doesn't exist, or an error message.
        """
        try:
            full_path = (self.memory_path / relative_path).resolve()
            # Ensure the full path is within plugin_data_path
            if not str(full_path).startswith(str(self.memory_path.resolve())):
                return "Error: Invalid path - cannot access outside memory directory"
            
            if not full_path.exists():
                logger.info(f"Directory not found: {full_path}")
                return "not found"
            
            if not full_path.is_dir():
                return "Error: Path is not a directory"
            
            entries = []
            for item in full_path.iterdir():
                if item.is_file():
                    try:
                        size = item.stat().st_size
                        entries.append(f"file: {item.name} ({size} bytes)")
                    except Exception as e:
                        entries.append(f"file: {item.name} (error getting size: {e})")
                elif item.is_dir():
                    entries.append(f"folder: {item.name}")
                else:
                    entries.append(f"other: {item.name}")
            
            if not entries:
                result = "empty directory"
            else:
                result = "\n".join(entries)
            
            logger.info(f"Listed files in: {full_path}, count: {len(entries)}")
            return result
        except Exception as e:
            logger.error(f"Error listing files: {e}")
            return f"Error: {str(e)}"

    def _get_self_prompt_file_path(self, event: AstrMessageEvent) -> str:
        """Helper function to get the path to the self prompt file for the current bot.
        
        Returns:
            string: The file path (bot's self_id + ".md")
        """
        try:
            # Get the bot's self_id from the message object
            self_id = event.message_obj.self_id
            if not self_id:
                return None
            file_path = f"{self_id}.md"
            return file_path
        except Exception as e:
            logger.error(f"Error getting self prompt file path: {e}")
            return None

    @llm_tool(name="get_self_prompt_file_path")
    async def get_self_prompt_file_path(self, event: AstrMessageEvent) -> str:
        """Get the path to the self prompt file for the current bot.
        
        Returns:
            string: The file path (bot's self_id + ".md") or an error message
        """
        file_path = self._get_self_prompt_file_path(event)
        if file_path is None:
            return "Error: Could not retrieve bot self_id"
        logger.info(f"Self prompt file path: {file_path}")
        return file_path

    @llm_tool(name="upload_to_ai_memory")
    async def upload_to_ai_memory(self, event: AstrMessageEvent, relative_path: str) -> str:
        """Upload or Delete a memory entry to the "ai-memory" knowledge base
        
        Before uploading, this tool will delete any existing documents in the knowledge base that have the same path as the memory entry being uploaded.
        To delete a memory entry from the knowledge base, remove the local memory entry first then invoke this tool using the with the same path, the tool will attempt to delete any document with the same path in the knowledge base and return a message suggesting file not found.

        Args:
            relative_path (string): The relative file path to upload. The file must exist in the plugin's data directory.
            
        Returns:
            string: execution details when successful, otherwise an error message.
        """
        try:
            response = ""

            # Get the full path and ensure it's within plugin data directory
            full_path = (self.memory_path / relative_path).resolve()
            if not str(full_path).startswith(str(self.memory_path.resolve())):
                return "Error: Invalid path - cannot access outside memory directory"
            
            # Get the knowledge base manager from context
            if not hasattr(self.context, 'kb_manager'):
                return "Error: Knowledge base manager not available"
            
            # Find the "ai-memory" knowledge base
            kb_helper = await self.context.kb_manager.get_kb_by_name("ai-memory")
            if not kb_helper:
                return "Error: 'ai-memory' knowledge base not found. Please ensure it exists and is properly configured."
            
            # First, list all existing documents and delete those with the same name
            try:
                existing_docs = await kb_helper.list_documents()
                deleted_count = 0
                for doc in existing_docs:
                    if doc.doc_name == relative_path:
                        await kb_helper.delete_document(doc.doc_id)
                        deleted_count += 1
                        logger.info(f"Deleted existing document with name '{relative_path}' (ID: {doc.doc_id})")
                
                if deleted_count > 0:
                    logger.info(f"Deleted {deleted_count} existing document(s) with the same name before upload")
                    response += f"Deleted {deleted_count} existing document(s) with the same name before upload. "
            except Exception as list_error:
                logger.warning(f"Error while listing/deleting existing documents: {list_error}. Continuing with upload...")
            
            # Check if file exists
            if not full_path.exists() or not full_path.is_file():
                response += f"File not found at {relative_path} when attempting to upload."
                return response
            
            # Read file content as bytes
            file_content = full_path.read_bytes()
            
            # Determine file type from extension
            file_type = full_path.suffix.lstrip('.').lower()
            if not file_type:
                file_type = "txt"  # Default to text if no extension

            
            # Upload the document
            try:
                doc = await kb_helper.upload_document(
                    file_name=relative_path,
                    file_content=file_content,
                    file_type=file_type,
                    chunk_size=1024,  # Default values
                    chunk_overlap=50,
                    batch_size=32,
                    tasks_limit=3,
                    max_retries=3,
                    progress_callback=None,
                    pre_chunked_text=None,
                )
                logger.info(f"Successfully uploaded {relative_path} to ai-memory knowledge base. Document ID: {doc.doc_id}")
                return response + f"OK: Uploaded {relative_path} to ai-memory knowledge base. Document ID: {doc.doc_id}"
            except Exception as upload_error:
                logger.error(f"Error uploading document: {upload_error}")
                return response + f"Error uploading document: {str(upload_error)}"
                
        except Exception as e:
            logger.error(f"Error in upload_to_ai_memory: {e}")
            return response + f"Error: {str(e)}"

    # 注册指令的装饰器。指令名为 listtools。注册成功后，发送 `/listtools` 就会触发这个指令，并列出当前可用的工具
    @filter.command("listtools")
    async def listtools(self, event: AstrMessageEvent):
        """列出当前可用的工具列表""" # 这是 handler 的描述，将会被解析方便用户了解插件内容。建议填写。
        try:
            # Get the tool manager
            tool_manager = self.context.get_llm_tool_manager()
            # Get all tools
            all_tools = tool_manager.func_list
            # Filter active tools
            active_tools = [tool for tool in all_tools if getattr(tool, 'active', True)]
            
            if not active_tools:
                yield event.plain_result("当前没有可用的工具。")
                return
            
            # Format the tool list
            tool_list = []
            for i, tool in enumerate(active_tools, 1):
                name = getattr(tool, 'name', 'Unknown')
                tool_list.append(f"{i}. {name}")
            
            result = "当前可用的工具:\n" + "\n".join(tool_list)
            yield event.plain_result(result)
            
        except Exception as e:
            logger.error(f"Error listing tools: {e}")
            yield event.plain_result(f"获取工具列表时出错: {str(e)}")
