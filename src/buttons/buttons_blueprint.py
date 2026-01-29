#!/usr/bin/env python3
"""Button Actions Blueprint

Example blueprint showing how to integrate button presses with InkyPi actions.
This can be extended to trigger refreshes, change plugins, navigate, etc.
"""

import logging
from flask import Blueprint, current_app

logger = logging.getLogger(__name__)

buttons_bp = Blueprint("buttons", __name__, url_prefix="/api/buttons")


def setup_button_handlers(button_manager, refresh_task, device_config):
    """
    Set up button handlers for the InkyPi application.

    Args:
        button_manager: ButtonManager instance
        refresh_task: RefreshTask instance
        device_config: Config instance
    """

    def log_on_button_press(label):
        logger.info(f"Button {label} pressed")
        pass


    # Register the handlers
    button_manager.register_handler("A", log_on_button_press)
    button_manager.register_handler("B", log_on_button_press)
    button_manager.register_handler("C", log_on_button_press)
    button_manager.register_handler("D", log_on_button_press)

    logger.info("Button handlers registered")


@buttons_bp.route("/status", methods=["GET"])
def button_status():
    """Get button manager status"""
    button_manager = current_app.config.get("BUTTON_MANAGER")

    if not button_manager:
        return {"enabled": False, "message": "Button manager not available"}

    return {
        "enabled": button_manager.enabled,
        "running": button_manager.running,
        "buttons": button_manager.LABELS,
    }
