from astrbot.api.event import filter, AstrMessageEvent, MessageEventResult
from astrbot.api.star import Context, Star, register
from astrbot.api import logger
from astrbot.core.agent.message import TextPart
from astrbot.core.provider.entities import ProviderRequest
import datetime
import zoneinfo

@register("helloworld", "YourName", "一个简单的 Hello World 插件", "1.0.0")
class MyPlugin(Star):
    def __init__(self, context: Context):
        super().__init__(context)

    @filter.on_llm_request()
    async def on_llm_request(self, event: AstrMessageEvent, req: ProviderRequest):
        """Event handler for LLM requests to append UTC timestamp and role to extra_user_content_parts."""
        try:
            # Parse the current time in UTC
            try:
                now_utc = datetime.datetime.now(zoneinfo.ZoneInfo('UTC'))
                current_time_utc = now_utc.strftime("%Y-%m-%d %H:%M (%Z)")
                
                # Prepare the system reminder lines
                system_parts = []
                system_parts.append(f"Current datetime: {current_time_utc}")
                
                # Add role if event has role attribute
                # Note: Looking at the event structure, we might need to check for role differently
                # The original code checks if hasattr(event, 'role') and event.role
                # But based on the context.py structure, we should check the message object
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
                
                logger.debug(f"Appended UTC system reminder to extra_user_content_parts: {current_time_utc}")
                
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
