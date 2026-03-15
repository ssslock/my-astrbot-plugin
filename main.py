from astrbot.api.event import filter, AstrMessageEvent, MessageEventResult
from astrbot.api.star import Context, Star, register
from astrbot.api import logger
from astrbot.core.agent.message import TextPart
import importlib
import inspect
import datetime
import zoneinfo

@register("helloworld", "YourName", "一个简单的 Hello World 插件", "1.0.0")
class MyPlugin(Star):
    def __init__(self, context: Context):
        super().__init__(context)
        self._original_append_system_reminders = None
        self._patched_module = None

    async def initialize(self):
        """可选择实现异步的插件初始化方法，当实例化该插件类之后会自动调用该方法。"""
        # Monkey patch _append_system_reminders (note: it's a function, not a method)
        try:
            # Import the module containing the function
            module = importlib.import_module('astrbot.core.astr_main_agent')
            self._patched_module = module
            
            # Save the original function
            if hasattr(module, '_append_system_reminders'):
                self._original_append_system_reminders = module._append_system_reminders
                
                # Create a wrapper function
                def patched_function(event, req, cfg, timezone):
                    # First, call the original function
                    logger.info("patched_function 1")
                    self._original_append_system_reminders(event, req, cfg, timezone)
                    
                    logger.info("patched_function 2")
                    # If event.role exists and is truthy, modify the system reminder
                    if hasattr(event, 'role'):
                        # Look for TextParts that contain system reminder
                        logger.info("patched_function 3")
                        for part in req.extra_user_content_parts:
                            logger.info("patched_function 4")
                            if isinstance(part, TextPart):
                                logger.info("patched_function 5")
                                text = part.text
                                logger.info("patched_function 6 - text: " + text)
                                # Check if this is a system reminder
                                if text.startswith('<system_reminder>') and text.endswith('</system_reminder>'):
                                    # Find the user identifier line and add role
                                    lines = text.split('\n')
                                    lines.append(f'Role: {event.role}')  # Add role as a new line
                                    part.text = '\n'.join(lines)
                                    logger.info(f"Added role {event.role} to system reminder")
                                    break
                
                # Replace the function in the module
                module._append_system_reminders = patched_function
                logger.info("Successfully patched _append_system_reminders")
            else:
                logger.warning("Could not find _append_system_reminders function in module")
                return
            
        except Exception as e:
            logger.error(f"Failed to monkey patch _append_system_reminders: {e}")

    async def terminate(self):
        """可选择实现异步的插件销毁方法，当插件被卸载/停用时会调用。"""
        # Restore the original function
        if self._patched_module is not None and self._original_append_system_reminders is not None:
            self._patched_module._append_system_reminders = self._original_append_system_reminders
            logger.info("Restored original _append_system_reminders")
