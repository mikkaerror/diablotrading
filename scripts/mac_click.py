#!/usr/bin/env python3
from __future__ import annotations

"""Minimal macOS mouse helper for controlled UI automation.

This utility uses CoreGraphics via ctypes so we can click specific screen
coordinates without bringing in extra dependencies. It is intentionally tiny
and local to the Inferno desk because we only need safe panel navigation inside
thinkorswim, not broad desktop automation.
"""

import argparse
import ctypes
import time
from ctypes import c_bool, c_double, c_uint32, c_void_p


CORE_GRAPHICS = ctypes.cdll.LoadLibrary(
    "/System/Library/Frameworks/ApplicationServices.framework/ApplicationServices"
)

CGEventRef = c_void_p
CGEventSourceRef = c_void_p

KCG_HID_EVENT_TAP = 0
KCG_EVENT_LEFT_MOUSE_DOWN = 1
KCG_EVENT_LEFT_MOUSE_UP = 2
KCG_EVENT_MOUSE_MOVED = 5
KCG_MOUSE_BUTTON_LEFT = 0


class CGPoint(ctypes.Structure):
    _fields_ = [("x", c_double), ("y", c_double)]


CORE_GRAPHICS.CGEventCreateMouseEvent.argtypes = [
    CGEventSourceRef,
    c_uint32,
    CGPoint,
    c_uint32,
]
CORE_GRAPHICS.CGEventCreateMouseEvent.restype = CGEventRef

CORE_GRAPHICS.CGEventPost.argtypes = [c_uint32, CGEventRef]
CORE_GRAPHICS.CGEventPost.restype = None

CORE_GRAPHICS.CFRelease.argtypes = [c_void_p]
CORE_GRAPHICS.CFRelease.restype = None

CORE_GRAPHICS.CGDisplayMoveCursorToPoint.argtypes = [c_uint32, CGPoint]
CORE_GRAPHICS.CGDisplayMoveCursorToPoint.restype = c_bool


def post_mouse_event(event_type: int, x: float, y: float) -> None:
    """Post a single CoreGraphics mouse event."""
    point = CGPoint(x=x, y=y)
    event = CORE_GRAPHICS.CGEventCreateMouseEvent(
        None,
        event_type,
        point,
        KCG_MOUSE_BUTTON_LEFT,
    )
    if not event:
        raise RuntimeError("failed to create mouse event")
    try:
        CORE_GRAPHICS.CGEventPost(KCG_HID_EVENT_TAP, event)
    finally:
        CORE_GRAPHICS.CFRelease(event)


def move_cursor(x: float, y: float) -> None:
    """Move the cursor to the requested point on the main display."""
    CORE_GRAPHICS.CGDisplayMoveCursorToPoint(0, CGPoint(x=x, y=y))


def click(x: float, y: float, pause: float = 0.06) -> None:
    """Perform a left click at the requested screen coordinate."""
    move_cursor(x, y)
    time.sleep(pause)
    post_mouse_event(KCG_EVENT_LEFT_MOUSE_DOWN, x, y)
    time.sleep(pause)
    post_mouse_event(KCG_EVENT_LEFT_MOUSE_UP, x, y)


def parse_args() -> argparse.Namespace:
    """Parse CLI arguments for the mouse helper."""
    parser = argparse.ArgumentParser(description="Click a macOS screen coordinate.")
    parser.add_argument("x", type=float, help="Screen x coordinate in macOS points")
    parser.add_argument("y", type=float, help="Screen y coordinate in macOS points")
    parser.add_argument("--pause", type=float, default=0.06, help="Pause between move/down/up")
    return parser.parse_args()


def main() -> int:
    """Run the CLI helper."""
    args = parse_args()
    click(args.x, args.y, pause=args.pause)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
