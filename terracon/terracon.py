#!/usr/bin/python3

import threading
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
import logging
import threading

gpio_present = True

version_major = 1
version_minor = 0
revision = 1

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

def short_class_name(class_type):
    return class_type.__name__

class Task:
    def __init__(self, name):
        self.name = name
        self.root = None
        self.is_done = False
        self.start_time_stamp = datetime.now()

    def short_class_name(self):
        return type(self).__name__

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
        self.prev_task_count = 0

    def load_program(self, module_name, dir_path='.'):
        module_full_path = dir_path + '/' + module_name
        logging.info("using scenario from module'{}'".format(module_full_path))
        code_object = None
        with open(module_full_path) as f:
            prog_text = f.read()
            code_object = compile(prog_text, 'none', 'exec')
            logging.info('executing code...')
            exec(code_object,
                 {"Task": Task, "TerraconProgramEngine": TerraconProgramEngine, "engine": self})

        return True

    def step(self):
        tmp_tasks = [task for task in self.tasks if not task.is_done]
        self.tasks = tmp_tasks
        cur_task_count = len(self.tasks)
        if cur_task_count != self.prev_task_count:
            logging.info("task count changed: {} -> {}".format(self.prev_task_count, cur_task_count))
            tasks_str = "tasks now: "
            for task in self.tasks:
                tasks_str += task.name
                tasks_str += "; "
            logging.info(tasks_str)

        self.prev_task_count = cur_task_count

        for task in self.tasks:
            task.step(self)

    def task_exists(self, task_name):
        for task in self.tasks:
            if task.name == task_name:
                return True
        return False

    def find_task(self, task_name):
        for task in self.tasks:
            if task.name == task_name:
                return task

    def new_task(self, task_class_type, task_name = ""):
        name = short_class_name(task_class_type)
        if task_name:
            name = task_name
        if self.find_task(name):
            return False
        task = task_class_type(name)
        task.root = self.root_task
        self.tasks.append(task)

        logging.info("new task {} of class {}".format(name, task_class_type))
        logging.info("tasks active: {}".format(len(self.tasks)))

    def current_time(self):
        now = datetime.now()
        return now.time()


class Worker:
    def __init__(self, use_gpio):
        self.use_gpio = use_gpio
        self.should_stop = False
        self.do_program_thread = False
        self.stop_webserver = None
        self.web_server = WebServer(self)
        self.main_light_intensity = 0
        self.water_on = False
        self.fogger_pump_on = False
        self.program_engine = TerraconProgramEngine(self)
        self.program_future = None  # объект Future для сценария
        self.active_program_name = 'program_test1.py'  #'no-active-program'
        self.script_mode = True
        self.script_mode_changed = False
        self.config_file_path = 'config.json'
        self.program_thread = None
        if not self.config_exists():
            self.write_config()
        self.read_config()

    def config_exists(self):
        try:
            open(self.config_file_path, "r")
        except FileNotFoundError:
            return False

        return True

    def read_config(self):
        data = None
        try:
            with open(self.config_file_path, "r") as read_file:
                data = json.load(read_file)
        except FileNotFoundError:
            logging.warning("Could not load config: file not found")
            return False

        self.parse_config(data)

        return True

    def parse_config(self, data):
        general = data["general"]
        if general:
            if "script_mode" in general:
                self.script_mode = general["script_mode"]

        return True

    def write_config(self):
        data = dict()
        general = {'script_mode': self.script_mode}
        data["general"] = general

        with open(self.config_file_path, "w") as write_file:
            json.dump(data, write_file)

        logging.info("configuration saved")

    def on_new_command(self, text):
        self.parse_command(text)

    async def run_server(self):
        logging.info('running webserver')
        loop = asyncio.get_running_loop()
        self.stop_webserver = loop.create_future()
        async with websockets.serve(self.web_server.ws_handler, "", 8001):
            await self.stop_webserver

    def program_thread_func(self):
        logging.info('starting program thread function')

        self.do_program_thread = True

        while self.do_program_thread:
            if self.script_mode_changed:
                if self.script_mode == True:
                    logging.info('starting program {}'.format(self.active_program_name))
                    self.program_engine.load_program(module_name=self.active_program_name, dir_path='./programs')

                self.script_mode_changed = False

            if self.script_mode:
                self.program_engine.step()

            time.sleep(0.1)

        logging.info('program thread function finished')

        return 0

    async def run_gpio(self):
        logging.info('running gpio')

        main_light_pin = 12     # GPIO12 - управление светом
        watering_pump_pin = 16  # GPIO16 - управление помпой верхнего полива
        fogger_pump_pin = 20    # GPIO20 - управление помпой туманогенератора

        GPIO.setmode(GPIO.BCM)    # устанавливаем режим нумерации по назв. каналов
        GPIO.setup(main_light_pin, GPIO.OUT)
        GPIO.setup(watering_pump_pin, GPIO.OUT)
        GPIO.setup(fogger_pump_pin, GPIO.OUT)

        pwm = GPIO.PWM(main_light_pin, 20000)  # устанавливаем частоту ШИМ 20 кГц
        GPIO.output(watering_pump_pin, GPIO.HIGH)  # помпа выключена
        GPIO.output(fogger_pump_pin, GPIO.HIGH)  # помпа выключена

        pwm.start(0)

        while not self.should_stop:
            # яркость основного освещения
            pwm.ChangeDutyCycle(self.main_light_intensity)

            # помпа верхнего полива
            if self.water_on:
                GPIO.output(watering_pump_pin, GPIO.LOW)  # включить помпу
            else:
                GPIO.output(watering_pump_pin, GPIO.HIGH)  # выключить помпу

            # помпа туманогенератора
            if self.fogger_pump_on:
                GPIO.output(fogger_pump_pin, GPIO.LOW)  # включить помпу
            else:
                GPIO.output(fogger_pump_pin, GPIO.HIGH)  # выключить помпу

            await asyncio.sleep(0.5)

        pwm.stop()
        GPIO.output(watering_pump_pin, GPIO.HIGH)  # выходя, выключаем помпу
        GPIO.output(fogger_pump_pin, GPIO.HIGH)  # выходя, выключаем помпу

        GPIO.cleanup()

        logging.info('gpio finished')

    def run(self):
        logging.info('-> run')

        logging.info('starting program thread...')
        self.program_thread = threading.Thread(target=self.program_thread_func)
        self.program_thread.start()
        logging.info('done')

        logging.info('starting async event loop')
        ioloop = asyncio.new_event_loop()
        asyncio.set_event_loop(ioloop)
        tasks = list()
        tasks.append(ioloop.create_task(self.run_server()))
        if self.use_gpio:
            tasks.append(ioloop.create_task(self.run_gpio()))
        wait_tasks = asyncio.wait(tasks)
        ioloop.run_until_complete(wait_tasks)
        ioloop.close()

        self.program_thread.join()

        logging.info('<- run')

    def set_light_intensity(self, value):
        if value < 0:
            value = 0
        if value > 100:
            value = 100
        self.main_light_intensity = value

    def parse_command(self, text: str):
        root = etree.fromstring(text)

        #print(root.tag, root.attrib)

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
            case "foggerPumpOn":
                self.on_command_fogger_pump_on(root)
            case "foggerPumpOff":
                self.on_command_fogger_pump_off(root)
            case "checkOnline":
                self.on_command_check_online(root)
            case "updateFromServer":
                self.on_command_update_from_server(root)
            case "serverShutdown":
                self.on_command_server_shutdown(root)
            case "setScriptMode":
                self.on_command_set_script_mode(root)
            case "setManualMode":
                self.on_command_set_manual_mode(root)
            case "getProgramList":
                self.on_command_get_program_list(root)
            case _:
                pass

    def on_command_set_light_intensity(self, elem):
        if self.script_mode:
            logging.info("External command 'Set light intensity' cannot be executed in Script mode")
            return False

        if elem.text:
            value = int(elem.text)
            self.set_light_intensity(value)
            logging.info("new light intensity: {}".format(value))

    def on_command_water_on(self, elem):
        self.water_on = True

    def on_command_water_off(self, elem):
        self.water_on = False

    def on_command_fogger_pump_on(self, elem):
        self.fogger_pump_on = True

    def on_command_fogger_pump_off(self, elem):
        self.fogger_pump_on = False

    def on_command_check_online(self, elem):
        cmd_text = self.make_command_report_online()
        cur_loop = asyncio.get_event_loop()
        asyncio.run_coroutine_threadsafe(self.web_server.send_to_client(cmd_text), cur_loop)

    def on_command_update_from_server(self, elem):
        cmd_text = self.make_command_server_status()
        cur_loop = asyncio.get_event_loop()
        asyncio.run_coroutine_threadsafe(self.web_server.send_to_client(cmd_text), cur_loop)

    def make_command_report_online(self):
        dom = md.getDOMImplementation()
        doc = dom.createDocument(None, None, None)
        root = doc.createElement("command")
        root.setAttribute("opcode", "reportOnline")
        doc.appendChild(root)

        return doc.toxml()

    def make_command_server_status(self):
        dom = md.getDOMImplementation()
        doc = dom.createDocument(None, None, None)
        root = doc.createElement("command")
        root.setAttribute("opcode", "serverStatus")
        doc.appendChild(root)

        elem = doc.createElement("version")
        root.appendChild(elem)
        txt = "{}.{}.{}".format(version_major, version_minor, revision)
        valElem = doc.createTextNode(txt)
        elem.appendChild(valElem)

        elem = doc.createElement("mode")
        root.appendChild(elem)
        txt = "script" if self.script_mode else "manual"
        valElem = doc.createTextNode(txt)
        elem.appendChild(valElem)

        elem = doc.createElement("lightIntensity")
        root.appendChild(elem)
        valElem = doc.createTextNode(str(self.main_light_intensity))
        elem.appendChild(valElem)

        elem = doc.createElement("waterOn")
        root.appendChild(elem)
        txt = 'true' if self.water_on else 'false'
        valElem = doc.createTextNode(txt)
        elem.appendChild(valElem)

        return doc.toxml()

    def shutdown(self):
        self.write_config(self.config_file_path)
        self.do_program_thread = False
        self.should_stop = True  # TODO сделать аккуратное завершение
        self.stop_webserver.set_result(True)

    def set_script_mode(self):
        if self.script_mode == True:
            return  # уже в нужном режиме
        self.script_mode = True
        self.script_mode_changed = True

    def set_manual_mode(self):
        if self.script_mode == False:
            return  # уже в нужном режиме
        self.script_mode = False
        self.script_mode_changed = True

    def on_command_server_shutdown(self, elem):
        logging.info("shutdown command received")
        self.shutdown()

    def on_command_set_script_mode(self, elem):
        logging.info("Set script mode command received")
        self.set_script_mode()

    def on_command_set_manual_mode(self, elem):
        logging.info("Set manual mode command received")
        self.set_manual_mode()

    def on_command_get_program_list(self, elem):
        logging.info("Program list request received")
        cmd_text = self.make_command_get_program_list()
        cur_loop = asyncio.get_event_loop()
        asyncio.run_coroutine_threadsafe(self.web_server.send_to_client(cmd_text), cur_loop)

    def make_command_get_program_list(self):
        dom = md.getDOMImplementation()
        doc = dom.createDocument(None, None, None)
        root = doc.createElement("command")
        root.setAttribute("opcode", "programList")
        doc.appendChild(root)

        progs_elem = doc.createElement("programs")
        root.appendChild(progs_elem)

        '''for prog in progs:
            prog_elem = doc.createElement("program")
            progs_elem.appendChild(prog_elem)
            prog_name_elem.doc.createTextNode(str(prog.name))
            prog_elem.appendChild(prog_name_elem)
            '''

        active_prog_elem = doc.createElement("activeProgram")
        root.appendChild(active_prog_elem)
        valElem = doc.createTextNode(str(self.active_program_name))
        active_prog_elem.appendChild(valElem)

        return doc.toxml()

def handler_ctrl_c(worker, signum, frame):
    res = input("Exit program? y/N")
    if res == 'y' or res == 'Y':
        worker.shutdown()

def main():
    logging.basicConfig(level=logging.INFO, filename='terracon.log', filemode='a',
                        format="[%(asctime)s : %(levelname)s] %(message)s")

    logging.info("Program (re)started")

    worker = Worker(gpio_present)
    #signal.signal(signal.SIGINT, partial(handler_ctrl_c, worker))
    worker.run()

    logging.info("Exit")

main()

