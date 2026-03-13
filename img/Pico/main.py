# main.py — Startpunkt för stjärnhimmel-styrning (MicroPython, Raspberry Pi Pico W)
#
# Flashar du Pico W för första gången:
#   1. Ladda ned MicroPython UF2 från https://micropython.org/download/RPI_PICO_W/
#   2. Håll BOOTSEL intryckt, anslut USB → Pico dyker upp som USB-enhet
#   3. Dra UF2-filen till enheten
#   4. Kopiera dessa filer till Picon med Thonny eller mpremote:
#      main.py, animation.py, api.py, config.json
#   5. Starta om Picon — WiFi-IP visas i serial-konsollen (115200 baud)
#
# Kopplingsschema (direkt, utan transistorer):
#   GPIO → 330Ω → LED(anod), LED(katod) → GND
# Använd detta på alla 13 kanaler (GP0-GP12).

import json
import time
import network
import uasyncio as asyncio
from animation import AnimationController
from api import start_server


def load_config():
    try:
        with open("config.json", "r") as f:
            return json.load(f)
    except Exception:
        print("VARNING: config.json saknas eller ogiltig — ethernet inaktiverat")
        return {"ssid": "", "password": ""}


def connect_wifi(ssid, password, timeout_s=20):
    if not ssid:
        print("WiFi: inget SSID konfigurerat, hoppar över anslutning")
        return False

    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)

    if wlan.isconnected():
        print("WiFi: redan ansluten till", wlan.ifconfig()[0])
        return True

    print("WiFi: ansluter till", ssid, "...")
    wlan.connect(ssid, password)

    deadline = time.time() + timeout_s
    while not wlan.isconnected():
        if time.time() > deadline:
            print("WiFi: timeout — kunde inte ansluta")
            return False
        time.sleep(0.5)

    ip = wlan.ifconfig()[0]
    print("WiFi: ansluten!")
    print("  IP-adress:  ", ip)
    print("  API-URL:     http://{}/".format(ip))
    print("  Parametrar:  http://{}/params".format(ip))
    print("  Status:      http://{}/status".format(ip))
    return True


async def main():
    # 1. WiFi
    config = load_config()
    wifi_ok = connect_wifi(config.get("ssid", ""), config.get("password", ""))

    # 2. Animationskontroller
    controller = AnimationController()
    print("Seed:", controller.params["seed"], "— ordning:", controller.order)

    # 3. Starta animation + HTTP-server parallellt
    tasks = [controller.run()]
    if wifi_ok:
        tasks.append(start_server(controller, port=80))

    await asyncio.gather(*tasks)


asyncio.run(main())
