"""Pure allowlist validation shared by PocketPC and its elevated input helper."""
import math


def validated_mouse_event(message):
    if not isinstance(message, dict) or not isinstance(message.get("type"), str):
        raise ValueError("Invalid mouse event")
    kind = message["type"]
    if kind == "move" and set(message) == {"type", "dx", "dy"}:
        values = message["dx"], message["dy"]
        if any(isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) for value in values):
            raise ValueError("Invalid mouse movement")
        dx, dy = (int(round(float(value))) for value in values)
        if not -120 <= dx <= 120 or not -120 <= dy <= 120:
            raise ValueError("Mouse movement is too large")
        return "move", dx, dy
    if kind == "position" and set(message) == {"type", "x", "y"}:
        values = message["x"], message["y"]
        if any(isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) for value in values):
            raise ValueError("Invalid mouse position")
        x, y = map(float, values)
        if not 0 <= x <= 1 or not 0 <= y <= 1:
            raise ValueError("Mouse position is outside the approved display")
        return "position", x, y
    if kind == "click" and set(message) == {"type", "button"} and message["button"] in {"left", "right"}:
        return "click", message["button"]
    if (kind == "button" and set(message) == {"type", "button", "action"}
            and message["button"] == "left" and message["action"] in {"down", "up"}):
        return "button", "left", message["action"]
    if kind == "scroll" and set(message) == {"type", "dy"}:
        value = message["dy"]
        if isinstance(value, bool) or not isinstance(value, int) or not -5 <= value <= 5 or value == 0:
            raise ValueError("Invalid mouse scroll")
        return "scroll", value
    raise ValueError("Unsupported mouse event")
