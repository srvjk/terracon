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

class DoSunrise(Task):
    def __init__(self, name):
        super().__init__(name)
        self.light_intensity = float(0)
        self.min_light_intensity = float(0)
        self.max_light_intensity = float(100)
        self.duration = float(60)  # в секундах
        self.k = float(0)

    def step(self, engine):
        if self.k == 0:
            self.k = (self.max_light_intensity - self.min_light_intensity) / self.duration

        li = self.min_light_intensity + self.k * self.time_from_start_sec()
        if li > self.max_light_intensity:
            li = self.max_light_intensity

        self.light_intensity = li
        logging.info("light: {}".format(self.light_intensity))
        if self.light_intensity >= self.max_light_intensity:
            logging.info("Sunrise: light at max, finishing")
            self.finish()
        engine.worker.main_light_intensity = self.light_intensity  #TODO переделать через apply()

class DoSunset(Task):
    def __init__(self, name):
        super().__init__(name)
        self.light_intensity = float(0)
        self.min_light_intensity = float(0)
        self.max_light_intensity = float(100)
        self.duration = float(60)  # в секундах
        self.k = float(0)

    def step(self, engine):
        if self.k == 0:
            self.k = (self.min_light_intensity - self.max_light_intensity) / self.duration

        li = self.max_light_intensity + self.k * self.time_from_start_sec()
        if li < self.min_light_intensity:
            li = self.min_light_intensity

        self.light_intensity = li
        logging.info("light: {}".format(self.light_intensity))
        if self.light_intensity <= self.min_light_intensity:
            logging.info("Sunset: light at min, finishing")
            self.finish()
        engine.worker.main_light_intensity = self.light_intensity  #TODO переделать через apply()

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

        logging.info("new task {} of class {} at {}".format(name, task_class_type, self.current_time()))
        logging.info("tasks active: {}".format(len(self.tasks)))

    def clear_tasks(self):
        self.tasks.clear()
        self.root_task = None
        logging.info("task list is empty")

    def current_time(self):
        now = datetime.now()
        return now.time()


class Worker:
    def __init__(self, use_gpio):
        self.use_gpio = use_gpio
        self.gpio_ready = False
        self.should_stop = False
        self.do_program_thread = False
        self.stop_webserver = None
        self.web_server = WebServer(self)
        self.main_light_intensity = float()
        self.water_on = False
        self.fogger_pump_on = False
        self.program_engine = TerraconProgramEngine(self)
        self.program_future = None  # объект Future для сценария
        self.active_program_name = 'program_test1.py'  #'no-active-program'
        self.current_single_task: Task = None  # одиночн. задача, выполн. вне программы (напр., по команде с пульта)
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

        logging.info(">>> config")
        logging.info("... script mode: {}".format(self.script_mode))
        logging.info("<<< config")

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
        first_iteration = True
        iterations_counter = 0

        while self.do_program_thread:
            iterations_counter += 1

            # проверяем выполнение всех необходимых условий:
            ok = True
            if self.use_gpio:
                if not self.gpio_ready:
                    ok = False
            # если не все условия выполнены, пропускаем итерацию
            if not ok:
                time.sleep(0.1)
                continue

            if first_iteration:
                logging.info("program thread: all conditions met at iter {}, work started".format(iterations_counter))
            if self.script_mode_changed or first_iteration:
                if self.script_mode == True:
                    logging.info('starting program {}'.format(self.active_program_name))
                    self.program_engine.load_program(module_name=self.active_program_name, dir_path='./programs')

                self.script_mode_changed = False

            if self.script_mode:
                if not self.current_single_task:
                    self.program_engine.step()
                else:
                    logging.warning("single task running at script mode, skipping program step")
            else:
                if self.current_single_task:
                    self.current_single_task.step(self.program_engine)
                    if self.current_single_task.is_done:
                        self.current_single_task = None

            first_iteration = False
            time.sleep(0.1)

        logging.info('program thread function finished')

        return 0

    async def run_gpio(self):
        logging.info('running GPIO')
        self.gpio_ready = False

        min_light_duty_cycle = 0.0
        max_light_duty_cycle = 100.0

        main_light_pin = 12     # GPIO12 - управление светом
        watering_pump_pin = 16  # GPIO16 - управление помпой верхнего полива
        fogger_pump_pin = 20    # GPIO20 - управление помпой туманогенератора

        GPIO.setmode(GPIO.BCM)    # устанавливаем режим нумерации по назв. каналов
        GPIO.setup(main_light_pin, GPIO.OUT)
        GPIO.setup(watering_pump_pin, GPIO.OUT)
        GPIO.setup(fogger_pump_pin, GPIO.OUT)

        pwm = GPIO.PWM(main_light_pin, 470)  # это частота ШИМ на Raspberry! частота основного контроллера - 20 кГц
        # (Этот вывод Raspberry служит для управления дискретным высокочастотным ШИМ-контроллером, который управляет
        # яркостью светодиодных лент. Контроллеру на входе нужен уровень от 0 до 5 В, который и задает желаемую
        # скважность ШИМ. Значение частоты управляющего ШИМ взято не круглым, чтобы оно не резонировало с 20 кГц
        # и не создавало "алиасинг" в виде низкочастотных мерцаний при изменении яркости светодиодов.)
        GPIO.output(watering_pump_pin, GPIO.HIGH)  # помпа выключена
        GPIO.output(fogger_pump_pin, GPIO.HIGH)  # помпа выключена

        pwm.start(0)

        self.gpio_ready = True
        logging.info("GPIO ready")

        while not self.should_stop:
            # яркость основного освещения
            light_duty_cycle = 0
            if self.main_light_intensity > 0:
                light_duty_cycle = int(
                    min_light_duty_cycle + (max_light_duty_cycle - min_light_duty_cycle) * (self.main_light_intensity / 100.0)
                )

            pwm.ChangeDutyCycle(light_duty_cycle)

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

            await asyncio.sleep(0.05)

        pwm.stop()
        GPIO.output(watering_pump_pin, GPIO.HIGH)  # выходя, выключаем помпу
        GPIO.output(fogger_pump_pin, GPIO.HIGH)  # выходя, выключаем помпу

        GPIO.cleanup()

        logging.info('GPIO finished')
        self.gpio_ready = False

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
            case "doSunrise":
                self.on_command_do_sunrise(root)
            case "doSunset":
                self.on_command_do_sunset(root)
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
        self.write_config()
        self.do_program_thread = False
        self.should_stop = True  # TODO сделать аккуратное завершение
        self.stop_webserver.set_result(True)

    def set_script_mode(self):
        if self.script_mode == True:
            logging.info("already in script mode")
            return  # уже в нужном режиме
        self.script_mode = True
        self.script_mode_changed = True
        self.write_config()

    def set_manual_mode(self):
        if self.script_mode == False:
            logging.info("already in manual mode")
            return  # уже в нужном режиме
        self.script_mode = False
        self.script_mode_changed = True
        self.write_config()

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

    def on_command_do_sunrise(self, elem):
        logging.info("Sunrise command received")
        if self.script_mode == False:
            self.current_single_task = DoSunrise("Sunrise")

    def on_command_do_sunset(self, elem):
        logging.info("Sunset command received")
        if self.script_mode == False:
            self.current_single_task = DoSunset("Sunset")

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

