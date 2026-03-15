from astrbot.api.event import filter, AstrMessageEvent, MessageEventResult
from astrbot.api.star import Context, Star, register
from astrbot.api import logger
import importlib
import inspect

@register("helloworld", "YourName", "一个简单的 Hello World 插件", "1.0.0")
class MyPlugin(Star):
    def __init__(self, context: Context):
        super().__init__(context)
        self._original_append_system_reminder = None
        self._patched_class = None

    async def initialize(self):
        """可选择实现异步的插件初始化方法，当实例化该插件类之后会自动调用该方法。"""
        # Monkey patch _append_system_reminder
        try:
            # Import the module containing the class
            module = importlib.import_module('astrbot.core.astr_main_agent')
            # Find the class that contains _append_system_reminder
            # Look for a class with the method
            target_class = None
            for name in dir(module):
                obj = getattr(module, name)
                if isinstance(obj, type) and hasattr(obj, '_append_system_reminder'):
                    target_class = obj
                    break
            
            if target_class is None:
                logger.warning("Could not find class with _append_system_reminder method")
                return
            
            self._patched_class = target_class
            # Save the original method
            original_method = getattr(target_class, '_append_system_reminder')
            self._original_append_system_reminder = original_method
            
            # Create a wrapper function
            # We need to capture original_method in a closure
            if inspect.iscoroutinefunction(original_method):
                async def patched_method(self_instance, *args, **kwargs):
                    logger.info("Custom _append_system_reminder called (async)")
                    # Add your custom logic here
                    # For now, just call the original
                    return await original_method(self_instance, *args, **kwargs)
            else:
                def patched_method(self_instance, *args, **kwargs):
                    logger.info("Custom _append_system_reminder called (sync)")
                    # Add your custom logic here
                    # For now, just call the original
                    return original_method(self_instance, *args, **kwargs)
            
            # Replace the method
            setattr(target_class, '_append_system_reminder', patched_method)
            logger.info("Successfully patched _append_system_reminder")
            
        except Exception as e:
            logger.error(f"Failed to monkey patch _append_system_reminder: {e}")

    @filter.event_message_type(filter.EventMessageType.ALL)
    async def on_all_message(self, event: AstrMessageEvent):
        logger.info("setting role")
        event.message_obj.role = event.role # 用户的角色
        logger.info(f"role set: {event.message_obj.role} with {event.role}")

    async def terminate(self):
        """可选择实现异步的插件销毁方法，当插件被卸载/停用时会调用。"""
        # Restore the original method
        if self._patched_class is not None and self._original_append_system_reminder is not None:
            setattr(self._patched_class, '_append_system_reminder', self._original_append_system_reminder)
            logger.info("Restored original _append_system_reminder")
