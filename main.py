from astrbot.api.event import filter, AstrMessageEvent, MessageEventResult
from astrbot.api.star import Context, Star, register
from astrbot.api import logger
import importlib
import inspect

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
                    logger.info("Custom _append_system_reminders called")
                    # Add your custom logic here
                    # For example, you could modify the behavior before calling the original
                    
                    # You can inspect or modify parameters
                    logger.info(f"Event: {event}, Config: {cfg}, Timezone: {timezone}")
                    
                    # Call the original function
                    return self._original_append_system_reminders(event, req, cfg, timezone)
                
                # Replace the function in the module
                module._append_system_reminders = patched_function
                logger.info("Successfully patched _append_system_reminders")
            else:
                logger.warning("Could not find _append_system_reminders function in module")
                return
            
        except Exception as e:
            logger.error(f"Failed to monkey patch _append_system_reminders: {e}")

    @filter.event_message_type(filter.EventMessageType.ALL)
    async def on_all_message(self, event: AstrMessageEvent):
        logger.info("setting role")
        event.message_obj.role = event.role # 用户的角色
        logger.info(f"role set: {event.message_obj.role} with {event.role}")

    async def terminate(self):
        """可选择实现异步的插件销毁方法，当插件被卸载/停用时会调用。"""
        # Restore the original function
        if self._patched_module is not None and self._original_append_system_reminders is not None:
            self._patched_module._append_system_reminders = self._original_append_system_reminders
            logger.info("Restored original _append_system_reminders")
