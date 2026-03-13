# animation.py — Stjärnhimmel animationslogik (MicroPython, Raspberry Pi Pico W)
#
# GPIO-koppling (GP0–GP12):
#   Direktdrift utan transistorer.
#   Schema per kanal: GPIO → 330Ω → LED(anod), LED(katod) → GND
#   (samma upplägg för alla 13 kanaler)
#
# LED 0–11  = konstellationer A–L  (GP0–GP11)
# LED 12    = bakgrundsstjärnor X  (GP12)

import time
import math
import json
import uasyncio as asyncio
from machine import Pin, PWM

LAYER_COUNT = 12
FILLER_IDX  = 12          # GP12 = bakgrundsstjärnor
GPIO_PINS   = list(range(13))  # GP0 → GP12

DEFAULT_PARAMS = {
    "seed":          12345,
    "min_intensity": 40,
    "max_intensity": 255,
    "fade_ms":       2500,
    "hold_ms":       1800,
    "pause_ms":      700,
    "flicker_pct":   30,
}

# ---------------------------------------------------------------------------
# Mulberry32 — identisk implementation som i simulation.html och generate_poster.py
# ---------------------------------------------------------------------------
def mulberry32(seed):
    state = [int(seed) & 0xFFFFFFFF]
    def rand():
        state[0] = (state[0] + 0x6D2B79F5) & 0xFFFFFFFF
        z = state[0]
        z = ((z ^ (z >> 15)) * (z | 1)) & 0xFFFFFFFF
        z ^= (z + ((z ^ (z >> 7)) * ((z | 61) & 0xFFFFFFFF))) & 0xFFFFFFFF
        z = (z ^ (z >> 14)) & 0xFFFFFFFF
        return z / 0x100000000
    return rand


def build_order(seed):
    """Returnerar en Fisher-Yates-shufflad lista [0..11] med seed."""
    rand  = mulberry32(seed)
    order = list(range(LAYER_COUNT))
    for i in range(len(order) - 1, 0, -1):
        j = int(rand() * (i + 1))
        order[i], order[j] = order[j], order[i]
    return order


# ---------------------------------------------------------------------------
# Intensitetsberäkning — samma logik som getIntensityForLayer() i JS
# ---------------------------------------------------------------------------
def get_intensity_for_layer(layer_idx, order, t_ms, p):
    fade_ms  = p["fade_ms"]
    hold_ms  = p["hold_ms"]
    pause_ms = p["pause_ms"]
    min_i    = p["min_intensity"]
    max_i    = p["max_intensity"]

    cycle_ms    = fade_ms + hold_ms + fade_ms + pause_ms
    total_cycle = cycle_ms * LAYER_COUNT

    t   = t_ms % total_cycle
    pos = order.index(layer_idx)

    layer_start = pos * cycle_ms
    if t < layer_start or t >= layer_start + cycle_ms:
        return min_i

    local_t = t - layer_start

    if local_t < fade_ms:
        # Fade in
        return int(min_i + (max_i - min_i) * (local_t / fade_ms))
    elif local_t < fade_ms + hold_ms:
        # Hold
        return max_i
    elif local_t < 2 * fade_ms + hold_ms:
        # Fade out
        progress = (local_t - fade_ms - hold_ms) / fade_ms
        return int(max_i - (max_i - min_i) * progress)
    else:
        return min_i


def is_layer_active(layer_idx, order, t_ms, p):
    """True om lagret håller på att tona in/ut eller hålla."""
    fade_ms  = p["fade_ms"]
    hold_ms  = p["hold_ms"]
    cycle_ms = fade_ms + hold_ms + fade_ms + p["pause_ms"]
    t        = t_ms % (cycle_ms * LAYER_COUNT)
    pos      = order.index(layer_idx)
    local_t  = t - pos * cycle_ms
    return 0 <= local_t < 2 * fade_ms + hold_ms


def flicker_multiplier(led_idx, t_ms, amount):
    """Dubbelsinusvåg-flimmer, inaktiverat för aktiva lager."""
    if amount == 0:
        return 1.0
    f1 = math.sin(t_ms * 0.010 + led_idx * 1.3)
    f2 = math.sin(t_ms * 0.017 + led_idx * 2.7)
    scale = amount / 100.0
    return max(0.0, 1.0 - scale * ((f1 + f2 + 2) / 4))


# ---------------------------------------------------------------------------
# AnimationController
# ---------------------------------------------------------------------------
class AnimationController:

    def __init__(self):
        self._pwms = []
        for pin_idx in GPIO_PINS:
            p = PWM(Pin(pin_idx))
            p.freq(1000)
            p.duty_u16(0)
            self._pwms.append(p)

        self.params       = self._load_params()
        self.order        = build_order(self.params["seed"])
        self._start_ticks = time.ticks_ms()
        self._running     = True

    # --- Parameterhantering ---

    def _load_params(self):
        params = dict(DEFAULT_PARAMS)
        try:
            with open("params.json", "r") as f:
                params.update(json.load(f))
        except Exception:
            pass
        return params

    def save_params(self):
        with open("params.json", "w") as f:
            json.dump(self.params, f)

    def update_params(self, new_params):
        seed_changed = ("seed" in new_params and
                        int(new_params["seed"]) != self.params["seed"])
        # Typkonvertera numeriska värden
        for k, v in new_params.items():
            if k in self.params:
                self.params[k] = type(self.params[k])(v)
        if seed_changed:
            self.order        = build_order(self.params["seed"])
            self._start_ticks = time.ticks_ms()
        self.save_params()

    # --- PWM-hjälpare ---

    def _set_led(self, idx, intensity):
        duty = int(max(0, min(255, intensity)) / 255 * 65535)
        self._pwms[idx].duty_u16(duty)

    # --- Status för API ---

    def get_status(self):
        t_ms        = time.ticks_diff(time.ticks_ms(), self._start_ticks)
        cycle_ms    = (self.params["fade_ms"] + self.params["hold_ms"] +
                       self.params["fade_ms"] + self.params["pause_ms"])
        t           = t_ms % (cycle_ms * LAYER_COUNT)
        active_pos  = min(int(t // cycle_ms), LAYER_COUNT - 1)
        active_idx  = self.order[active_pos]
        return {
            "active_layer": active_idx,
            "active_label": chr(65 + active_idx),
            "t_ms":         t_ms,
        }

    # --- Animationsloop (~60 fps) ---

    async def run(self):
        while self._running:
            t_ms = time.ticks_diff(time.ticks_ms(), self._start_ticks)
            p    = self.params

            for layer_idx in range(LAYER_COUNT):
                intensity = get_intensity_for_layer(layer_idx, self.order, t_ms, p)
                if not is_layer_active(layer_idx, self.order, t_ms, p):
                    intensity = int(intensity * flicker_multiplier(
                        layer_idx, t_ms, p["flicker_pct"]))
                self._set_led(layer_idx, intensity)

            # Bakgrundsstjärnor — konstant min med flimmer
            bg = int(p["min_intensity"] * flicker_multiplier(
                FILLER_IDX, t_ms, p["flicker_pct"]))
            self._set_led(FILLER_IDX, bg)

            await asyncio.sleep_ms(16)
