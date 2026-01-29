#!/usr/bin/env python3
"""Button Manager for Inky Impression Display

Handles GPIO button input in a background thread to avoid blocking the Flask app.
Supports callback-based button press handling.
"""

import threading
import logging
from typing import Callable, Dict, Optional

try:
    import gpiod
    import gpiodevice
    from gpiod.line import Bias, Direction, Edge

    GPIOD_AVAILABLE = True
except ImportError:
    GPIOD_AVAILABLE = False

logger = logging.getLogger(__name__)


class ButtonManager:
    """Manages button input from Inky Impression display"""

    # GPIO pins for each button (from top to bottom)
    # Raspberry Pi 5 Header pins used by Inky Impression:
    # PIN29, PIN31, PIN36, PIN18 → GPIO05, GPIO06, GPIO16, GPIO24
    BUTTONS = [5, 6, 16, 24]
    LABELS = ["A", "B", "C", "D"]

    def __init__(self, enabled: bool = True):
        """
        Initialize the button manager.

        Args:
            enabled: Whether to enable button reading. Disable for testing/dev environments.
        """
        self.enabled = enabled and GPIOD_AVAILABLE
        self.thread = None
        self.running = False
        self.lock = threading.Lock()

        # Callback handlers for each button
        self.handlers: Dict[str, list[Callable]] = {label: [] for label in self.LABELS}

        self.request = None
        self.offsets = None

    def register_handler(self, button: str, callback: Callable) -> None:
        """
        Register a callback handler for a button press.

        Args:
            button: Button label ('A', 'B', 'C', or 'D')
            callback: Function to call when button is pressed.
                     Will receive the button label as argument.
        """
        if button not in self.LABELS:
            raise ValueError(f"Invalid button: {button}. Must be one of {self.LABELS}")

        with self.lock:
            self.handlers[button].append(callback)
            logger.info(f"Registered handler for button {button}")

    def unregister_handler(self, button: str, callback: Callable) -> None:
        """Unregister a callback handler."""
        if button in self.handlers and callback in self.handlers[button]:
            with self.lock:
                self.handlers[button].remove(callback)
                logger.info(f"Unregistered handler for button {button}")

    def start(self) -> bool:
        """
        Start listening for button presses.

        Returns:
            True if successfully started, False if disabled or already running
        """
        if not self.enabled:
            logger.warning(
                "Button manager is disabled (gpiod not available or disabled)"
            )
            return False

        if self.running:
            logger.warning("Button manager is already running")
            return False

        try:
            self._initialize_gpio()
            self.running = True
            self.thread = threading.Thread(target=self._run, daemon=True)
            self.thread.start()
            logger.info("Button manager started")
            return True
        except Exception as e:
            logger.error(f"Failed to start button manager: {e}")
            self.enabled = False
            return False

    def stop(self) -> None:
        """Stop listening for button presses."""
        with self.lock:
            self.running = False

        if self.thread:
            self.thread.join(timeout=2)
            logger.info("Button manager stopped")

        self._cleanup_gpio()

    def _initialize_gpio(self) -> None:
        """Initialize GPIO for button reading."""
        if not GPIOD_AVAILABLE:
            raise RuntimeError("gpiod not installed")

        input_settings = gpiod.LineSettings(
            direction=Direction.INPUT, bias=Bias.PULL_UP, edge_detection=Edge.FALLING
        )

        # Find the gpiochip device
        chip = gpiodevice.find_chip_by_platform()

        # Get line offsets for our buttons
        self.offsets = [chip.line_offset_from_id(btn) for btn in self.BUTTONS]

        # Build config for each pin
        line_config = dict.fromkeys(self.offsets, input_settings)

        # Request the lines
        self.request = chip.request_lines(consumer="inkypi-buttons", config=line_config)
        logger.info("GPIO initialized for button input")

    def _cleanup_gpio(self) -> None:
        """Clean up GPIO resources."""
        if self.request:
            try:
                self.request.release()
                self.request = None
            except Exception as e:
                logger.error(f"Error releasing GPIO: {e}")

    def _run(self) -> None:
        """Background thread that listens for button events."""
        try:
            while self.running:
                if not self.request:
                    break

                # Read edge events with a timeout to allow graceful shutdown
                try:
                    events = self.request.read_edge_events(timeout_ms=1000)
                except TypeError:
                    # Older/newer gpiod bindings may not accept timeout_ms
                    if hasattr(self.request, "wait_edge_events"):
                        if not self.request.wait_edge_events(timeout=1):
                            continue
                    events = self.request.read_edge_events()

                for event in events:
                    if not self.running:
                        break

                    self._handle_button_event(event)

        except Exception as e:
            logger.error(f"Error in button monitoring thread: {e}")
            self.running = False
        finally:
            self._cleanup_gpio()

    def _handle_button_event(self, event) -> None:
        """Handle a GPIO button event."""
        try:
            if self.offsets is None:
                return

            index = self.offsets.index(event.line_offset)
            gpio_number = self.BUTTONS[index]
            label = self.LABELS[index]

            logger.info(f"Button press detected: GPIO #{gpio_number} (Button {label})")

            # Call all registered handlers for this button
            with self.lock:
                handlers = self.handlers[label].copy()

            for handler in handlers:
                try:
                    handler(label)
                except Exception as e:
                    logger.error(f"Error calling button handler for {label}: {e}")

        except Exception as e:
            logger.error(f"Error handling button event: {e}")
