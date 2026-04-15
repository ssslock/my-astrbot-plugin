from astrbot.api.event import filter, AstrMessageEvent, MessageEventResult
from astrbot.api.star import Context, Star, register
from astrbot.api import logger
from astrbot.core.agent.message import TextPart
from astrbot.core.provider.entities import ProviderRequest
from datetime import datetime, timezone, timedelta
import asyncio
from pathlib import Path

@register("helloworld", "YourName", "一个简单的 Hello World 插件", "1.0.0")
class MyPlugin(Star):
    def __init__(self, context: Context):
        super().__init__(context)
        # Add conversation timezone storage
        self.conversation_timezone_path = Path(__file__).parent / "conversations"
        self.conversation_timezone_path.mkdir(parents=True, exist_ok=True)

    @filter.on_llm_request()
    async def on_llm_request(self, event: AstrMessageEvent, req: ProviderRequest):
        """Event handler for LLM requests to append local timestamp and role to extra_user_content_parts."""
        try:
            # Get conversation ID and timezone
            conv_mgr = self.context.conversation_manager
            umo = event.unified_msg_origin
            conversation_id = await conv_mgr.get_curr_conversation_id(umo)
            
            # Default to UTC+8 if no conversation exists or no timezone set
            timezone_offset = 8  # Default UTC+8
            
            if conversation_id:
                stored_offset = await self._get_conversation_timezone(conversation_id)
                if stored_offset is not None:
                    timezone_offset = stored_offset
            
            # Parse the current time in local timezone based on offset
            try:
                # Create timezone with the offset
                local_tz = timezone(timedelta(hours=timezone_offset))
                now_local = datetime.now(local_tz)
                
                # Format timezone string (e.g., UTC+8 or UTC-5)
                tz_sign = '+' if timezone_offset >= 0 else ''
                tz_str = f"UTC{tz_sign}{timezone_offset}"
                
                current_time_local = now_local.strftime(f"%Y-%m-%d %H:%M ({tz_str})")
                
                # Prepare the system reminder lines
                system_parts = []
                system_parts.append(f"Local datetime: {current_time_local}")
                
                # Add role if event has role attribute
                if hasattr(event.message_obj, 'sender') and hasattr(event.message_obj.sender, 'role'):
                    role = event.message_obj.sender.role
                    if role:
                        system_parts.append(f"Role: {role}")
                
                # Create the complete system reminder block in the same format as astr_main_agent.py
                system_content = "<system_reminder>" + "\n".join(system_parts) + "</system_reminder>"
                
                # Initialize extra_user_content_parts if None (safety check)
                if req.extra_user_content_parts is None:
                    req.extra_user_content_parts = []
                
                # Append to extra_user_content_parts as a TextPart
                req.extra_user_content_parts.append(TextPart(text=system_content))
                
                logger.debug(f"Appended local time system reminder to extra_user_content_parts: {current_time_local}")
                
            except Exception as e:
                logger.error(f"Error processing time for system reminder: {e}")
        except Exception as e:
            logger.error(f"Error in on_llm_request handler: {e}")

    async def initialize(self):
        """可选择实现异步的插件初始化方法，当实例化该插件类之后会自动调用该方法。"""
        logger.info("HelloWorld plugin initialized using event handler approach")

    async def terminate(self):
        """可选择实现异步的插件销毁方法，当插件被卸载/停用时会调用。"""
        logger.info("HelloWorld plugin terminated")

    async def _get_timezone_file_path(self, conversation_id: str) -> Path:
        """Get the file path for storing timezone for a conversation."""
        return self.conversation_timezone_path / f"{conversation_id}_timezone.txt"

    async def _set_conversation_timezone(self, conversation_id: str, timezone_offset: int) -> None:
        """Store timezone offset for a conversation."""
        if timezone_offset < -12 or timezone_offset > 14:
            raise ValueError("Timezone offset must be between -12 and 14")
        
        file_path = await self._get_timezone_file_path(conversation_id)
        file_path.write_text(str(timezone_offset), encoding='utf-8')
        logger.info(f"Set timezone offset {timezone_offset} for conversation {conversation_id}")

    async def _get_conversation_timezone(self, conversation_id: str) -> int | None:
        """Get timezone offset for a conversation."""
        file_path = await self._get_timezone_file_path(conversation_id)
        if file_path.exists():
            try:
                content = file_path.read_text(encoding='utf-8').strip()
                return int(content)
            except (ValueError, IOError) as e:
                logger.error(f"Error reading timezone for conversation {conversation_id}: {e}")
        return None

    @filter.command("set_timezone")
    async def set_timezone_command(self, event: AstrMessageEvent):
        """Set timezone offset for current conversation.
        
        Usage: /set_timezone <offset>
        Example: /set_timezone 8 (for UTC+8)
        Valid range: -12 to 14
        """
        try:
            # Parse the timezone offset from the message
            message_str = event.message_str.strip()
            parts = message_str.split()
            
            if len(parts) < 2:
                yield event.plain_result("Usage: /set_timezone <offset>\nExample: /set_timezone 8 (for UTC+8)\nValid range: -12 to 14")
                return
            
            try:
                timezone_offset = int(parts[1])
            except ValueError:
                yield event.plain_result(f"Invalid number: {parts[1]}. Please provide an integer between -12 and 14.")
                return
            
            # Validate range
            if timezone_offset < -12 or timezone_offset > 14:
                yield event.plain_result(f"Timezone offset must be between -12 and 14. Got: {timezone_offset}")
                return
            
            # Get current conversation ID
            conv_mgr = self.context.conversation_manager
            umo = event.unified_msg_origin
            conversation_id = await conv_mgr.get_curr_conversation_id(umo)
            
            if not conversation_id:
                # Create a new conversation if none exists
                conversation_id = await conv_mgr.new_conversation(umo, event.get_platform_id())
            
            # Store the timezone offset
            await self._set_conversation_timezone(conversation_id, timezone_offset)
            
            yield event.plain_result(f"Timezone offset set to UTC{'+' if timezone_offset >= 0 else ''}{timezone_offset} for this conversation.")
            
        except Exception as e:
            logger.error(f"Error in set_timezone command: {e}")
            yield event.plain_result(f"Error setting timezone: {str(e)}")

    @filter.command("get_timezone")
    async def get_timezone_command(self, event: AstrMessageEvent):
        """Get timezone offset for current conversation."""
        try:
            # Get current conversation ID
            conv_mgr = self.context.conversation_manager
            umo = event.unified_msg_origin
            conversation_id = await conv_mgr.get_curr_conversation_id(umo)
            
            if not conversation_id:
                yield event.plain_result("No active conversation found.")
                return
            
            # Get the timezone offset
            timezone_offset = await self._get_conversation_timezone(conversation_id)
            
            if timezone_offset is None:
                yield event.plain_result("No timezone set for this conversation. Use /set_timezone <offset> to set one.")
            else:
                yield event.plain_result(f"Current timezone offset: UTC{'+' if timezone_offset >= 0 else ''}{timezone_offset}")
                
        except Exception as e:
            logger.error(f"Error in get_timezone command: {e}")
            yield event.plain_result(f"Error getting timezone: {str(e)}")
