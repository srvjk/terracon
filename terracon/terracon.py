#!/usr/bin/python3

import time
import signal
import asyncio
import websockets
import xml.etree.ElementTree as etree
import xml.dom.minidom as md
import json
from functools import partial
from datetime import datetime
import importlib
import importlib.util


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


class Task:
    def __init__(self, name):
        self.name = name
        self.root = None
        self.is_done = False
        self.start_time_stamp = datetime.now()

    def time_from_start_sec(self):
        delta = datetime.now() - self.start_time_stamp
        s = delta.total_seconds()
        return s

    def step(self, engine):
        pass

    def finish(self):
        self.is_done = True


class TerraconProgramEngine:
    def __init__(self, worker):
        self.should_stop = False
        self.program = None
        self.tasks = list()
        self.root_task = None
        self.worker = worker

    def load_program(self, module_name, dir_path='.'):
        module_full_path = dir_path + '/' + module_name
        module_spec = importlib.util.spec_from_file_location(module_name, module_full_path)
        if module_spec is None:
            print('Module {} not found in {}'.format(module_name, dir_path))
            return False
        module = importlib.util.module_from_spec(module_spec)
        if module is None:
            return False
        module_spec.loader.exec_module(module)
        self.program = module
        self.root_task = self.program.RootTask("root")
        if not self.root_task:
            print("No root task found")
            return False
        self.tasks.append(self.root_task)

        return True

    def step(self):
        tmp_tasks = [task for task in self.tasks if not task.is_done]
        self.tasks = tmp_tasks

        for task in self.tasks:
            task.step(self)

    def find_task(self, task_name):
        for task in self.tasks:
            if task.name == task_name:
                return task

    def new_task(self, class_name, task_name = ""):
        name = class_name
        if task_name:
            name = task_name
        if self.find_task(name):
            return False
        task = class_name(name)
        task.root = self.root_task
        self.tasks.append(task)

    def current_time(self):
        now = datetime.now()
        return now.time()


class Worker:
    def __init__(self, use_gpio):
        self.use_gpio = use_gpio
        self.should_stop = False
        self.stop_webserver = None
        self.web_server = WebServer(self)
        self.main_light_intensity = 0
        self.water_on = False
        self.program_engine = TerraconProgramEngine(self)
        self.script_mode = True
        self.config_file_path = 'config.json'
        self.read_config(self.config_file_path)

    def read_config(self, file_name):
        data = None
        try:
            with open(file_name, "r") as read_file:
                data = json.load(read_file)
        except FileNotFoundError:
            print("Could not load config: file not found")
            return

        self.parse_config(data)

    def parse_config(self, data):
        general = data["general"]
        if general:
            if "script_mode" in general:
                self.script_mode = general["script_mode"]

        return True

    def write_config(self, file_name):
        data = dict()
        general = {'script_mode': self.script_mode}
        data["general"] = general

        with open(file_name, "w") as write_file:
            json.dump(data, write_file)

        print("configuration saved")

    def on_new_command(self, text):
        self.parse_command(text)

    async def run_server(self):
        print('running webserver')
        loop = asyncio.get_running_loop()
        self.stop_webserver = loop.create_future()
        async with websockets.serve(self.web_server.ws_handler, "", 8001):
            await self.stop_webserver

    async def run_program(self):
        print('running program engine')

        while not self.should_stop:
            if self.script_mode:
                self.program_engine.step()
            await asyncio.sleep(0.1)

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

    def set_light_intensity(self, value):
        if value < 0:
            value = 0
        if value > 100:
            value = 100
        self.main_light_intensity = value

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
            case "setScriptMode":
                self.on_command_set_script_mode(root)
            case "setManualMode":
                self.on_command_set_manual_mode(root)
            case _:
                pass

    def on_command_set_light_intensity(self, elem):
        if self.script_mode:
            print("External command 'Set light intensity' cannot be executed in Script mode")
            return False

        if elem.text:
            value = int(elem.text)
            self.set_light_intensity(value)
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

    def shutdown(self):
        self.write_config(self.config_file_path)
        self.should_stop = True  # TODO сделать аккуратное завершение
        self.stop_webserver.set_result(True)

    def set_script_mode(self):
        self.script_mode = True

    def set_manual_mode(self):
        self.script_mode = False

    def set_script_mode(self):
        self.script_mode = True

    def set_manual_mode(self):
        self.script_mode = False

    def on_command_server_shutdown(self, elem):
        print("Shutdown command received")
        self.shutdown()

    def on_command_set_script_mode(self, elem):
        print("Set script mode command received")
        self.set_script_mode()

    def on_command_set_manual_mode(self, elem):
        print("Set manual mode command received")
        self.set_manual_mode()

def handler_ctrl_c(worker, signum, frame):
    res = input("Exit program? y/N")
    if res == 'y' or res == 'Y':
        worker.shutdown()

def main():
    worker = Worker(gpio_present)
    signal.signal(signal.SIGINT, partial(handler_ctrl_c, worker))
    worker.run()

main()

print("exit")
