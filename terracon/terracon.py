#!/usr/bin/python3

import time
import asyncio
import websockets
import xml.etree.ElementTree as etree
import xml.dom.minidom as md
import terracon_program_engine as progengine

gpio_present = True

try:
    import RPi.GPIO as GPIO
except ModuleNotFoundError:
    gpio_present = False
    print("Error importing RPi.GPIO!")


class WebServer:
    def __init__(self, worker):
        self.client = None
        self.worker = worker

    async def register(self, ws: websockets.WebSocketServerProtocol) -> None:
        self.client = ws
        print("Client connected: {}".format(ws.remote_address))

    async def unregister(self, ws: websockets.WebSocketServerProtocol) -> None:
        self.client = None
        print("Client disconnected: {}".format(ws.remote_address))

    async def process_command(self, ws: websockets.WebSocketServerProtocol):
        async for message in ws:
            self.worker.on_new_command(message)

    async def ws_handler(self, ws: websockets.WebSocketServerProtocol, uri: str) -> None:
        await self.register(ws)
        try:
            await self.process_command(ws)
        finally:
            await self.unregister(ws)

    async def send_to_client(self, message: str) -> None:
        await self.client.send(message)

class Worker:
    def __init__(self, use_gpio):
        self.use_gpio = use_gpio
        self.should_stop = False
        self.web_server = WebServer(self)
        self.main_light_intensity = 0
        self.water_on = False
        self.program_engine = progengine.TerraconProgramEngine()
        self.enable_program = True

    def on_new_command(self, text):
        self.parse_command(text)

    async def run_server(self):
        print('running webserver')
        async with websockets.serve(self.web_server.ws_handler, "", 8001):
            await asyncio.Future()

    async def run_program(self):
        print('running program engine')

        while not self.should_stop:
            if not self.enable_program:
                time.sleep(0.1)
                continue
            self.program_engine.step()

        print ('program engine finished')

    async def run_gpio(self):
        print('running gpio')

        GPIO.setmode(GPIO.BCM)    # устанавливаем режим нумерации по назв. каналов
        GPIO.setup(12, GPIO.OUT)  # назначаем пин GPIO12 выходным (управление светом)
        GPIO.setup(16, GPIO.OUT)  # назначаем пин GPIO16 выходным (управление водяной помпой)

        pwm = GPIO.PWM(12, 20000)  # устанавливаем частоту ШИМ 20 кГц
        GPIO.output(16, GPIO.HIGH)  # помпа выключена

        pwm.start(0)

        while not self.should_stop:
            # яркость основного освещения
            pwm.ChangeDutyCycle(self.main_light_intensity)

            # водяная помпа верхнего полива
            if self.water_on:
                GPIO.output(16, GPIO.LOW)  # включить помпу
            else:
                GPIO.output(16, GPIO.HIGH)  # выключить помпу

            await asyncio.sleep(0.5)

        pwm.stop()
        GPIO.output(16, GPIO.HIGH)  # выходя, выключаем помпу

        GPIO.cleanup()

        print('gpio finished')

    def run(self):
        print('-> main')
        if not self.program_engine.load_program("program_test1.py", "./programs"):
            print("Error: could not load program")

        ioloop = asyncio.get_event_loop()
        tasks = list()
        tasks.append(ioloop.create_task(self.run_server()))
        tasks.append(ioloop.create_task(self.run_program()))
        if self.use_gpio:
            tasks.append(ioloop.create_task(self.run_gpio()))
        wait_tasks = asyncio.wait(tasks)
        ioloop.run_until_complete(wait_tasks)
        ioloop.close()
        print('<- main')

    def parse_command(self, text: str):
        root = etree.fromstring(text)

        print(root.tag, root.attrib)

        if root.tag != "command":
            return

        opcode = root.attrib["opcode"]
        if not opcode:
            return

        match opcode:
            case "setLightIntensity":
                self.on_command_set_light_intensity(root)
            case "waterOn":
                self.on_command_water_on(root)
            case "waterOff":
                self.on_command_water_off(root)
            case "updateFromServer":
                self.on_command_update_from_server(root)
            case "serverShutdown":
                self.on_command_server_shutdown(root)
            case _:
                pass

    def on_command_set_light_intensity(self, elem):
        if elem.text:
            value = int(elem.text)
            if 0 <= value <= 100:
                self.main_light_intensity = value
                print("new light intensity: {}".format(value))

    def on_command_water_on(self, elem):
        self.water_on = True

    def on_command_water_off(self, elem):
        self.water_on = False

    def on_command_update_from_server(self, elem):
        print(">>>")
        cmd_text = self.make_command_server_status()
        print("reply to client: {}".format(cmd_text))
        cur_loop = asyncio.get_event_loop()
        asyncio.run_coroutine_threadsafe(self.web_server.send_to_client(cmd_text), cur_loop)

    def make_command_server_status(self):
        dom = md.getDOMImplementation()
        doc = dom.createDocument(None, None, None)
        root = doc.createElement("command")
        root.setAttribute("opcode", "ServerStatus")
        doc.appendChild(root)

        elem = doc.createElement("lightIntensity")
        root.appendChild(elem)
        valElem = doc.createTextNode('99')
        elem.appendChild(valElem)

        elem = doc.createElement("waterOn")
        root.appendChild(elem)
        valElem = doc.createTextNode('false')
        elem.appendChild(valElem)

        return doc.toxml()

    def on_command_server_shutdown(self, elem):
        print("Shutdown command received")
        quit(0)

def main():
    worker = Worker(gpio_present)
    worker.run()

main()

print("exit")
