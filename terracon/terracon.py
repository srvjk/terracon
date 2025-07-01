#!/usr/bin/python3
import base64
import threading
import time
import signal
import argparse
import asyncio
from json import JSONDecodeError
from secrets import DEFAULT_ENTROPY

import websockets
#import xml.etree.ElementTree as etree
import xml.dom.minidom as md
import json
from functools import partial
from datetime import datetime
import importlib
import importlib.util
import logging
import threading
import hashlib
from cryptography.hazmat.primitives import serialization, hashes
from cryptography.hazmat.primitives.asymmetric import rsa, padding

gpio_present = True

version_major = 1
version_minor = 0
revision = 1

''' Таймаут по умолчанию для пользовательских сессий, в секундах '''
DEFAULT_USER_SESSION_TIMEOUT = 1 * 60.0

try:
    import RPi.GPIO as GPIO
except ModuleNotFoundError:
    gpio_present = False
    logging.error("Error importing RPi.GPIO!")


def make_hash(data: str):
    data_bytes = data.encode('utf-8')
    hash = hashlib.sha256(data_bytes).hexdigest()
    return hash


class WebServer:
    def __init__(self, worker):
        self.client = None
        self.worker = worker
        self.private_key = None
        self.init_cryptography()

    async def register(self, ws: websockets.WebSocketServerProtocol) -> None:
        self.client = ws
        logging.info("Client connected: {}".format(ws.remote_address))

    async def unregister(self, ws: websockets.WebSocketServerProtocol) -> None:
        self.client = None
        logging.info("Client disconnected: {}".format(ws.remote_address))

    async def process_command(self, ws: websockets.WebSocketServerProtocol):
        async for message in ws:
            self.worker.on_new_command(message)

    async def ws_handler(self, ws: websockets.WebSocketServerProtocol) -> None:
        await self.register(ws)
        try:
            await self.process_command(ws)
        finally:
            await self.unregister(ws)

    async def send_to_client(self, message: str) -> None:
        await self.client.send(message)

    def init_cryptography(self):
        try:
            with open("keys/terraconprivkey.pem", "rb") as key_file:
                logging.info("key file found")
                data = key_file.read()
                print(data)
                self.private_key = serialization.load_pem_private_key(data, password=None)
                logging.info("encryption key loaded")
        except IOError as err:
            logging.error("problem with encryption key file: " + str(err))
        except ValueError as err:
            logging.error("problem with encryption key: " + str(err))

def short_class_name(class_type):
    return class_type.__name__


class Task:
    """ Абстрактное задание - базовый класс для всех конкретных заданий и пользовательских сессий """
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


class UserSession(Task):
    """ Пользовательская сессия """
    def __init__(self, name):
        super().__init__(name)
        self.timeout = DEFAULT_USER_SESSION_TIMEOUT
        self.last_time_stamp = datetime.now()

    def expired(self)->bool:
        '''
        Проверка, не истекла ли сессия.
        Сессия считается истекшей, если пользователь не проявлял активности в течение заданного времени.
        '''
        idle_time = datetime.now() - self.last_time_stamp
        idle_time_sec = idle_time.total_seconds()
        if idle_time_sec >= self.timeout:
            return True
        return False

    def refresh(self):
        ''' Обнуление возраста сессии (например, если пришли данные от пользователя)'''
        self.last_time_stamp = datetime.now()

    def step(self, engine):
        pass


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


class User:
    def __init__(self, login, password_hash):
        self.login = login
        self.full_name = ""
        self.password_hash = password_hash

    def toJSON(self):
        return {"login": self.login, "password_hash": self.password_hash, "full_name": self.full_name}

def custom_serializer(obj):
    if hasattr(obj, 'toJSON')  and callable(obj.toJSON):
        return obj.toJSON()
    raise TypeError(f"Object of type {obj.__class__.__name__} is not JSON serializable")


class Worker:
    def __init__(self, use_gpio):
        self.use_gpio = use_gpio
        self.gpio_ready = False
        self.should_stop = False
        self.do_administration_thread = False
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
        self.script_mode = False
        self.script_mode_changed = False
        self.administration_thread = None
        self.program_thread = None
        self.config_file_path = 'config.json'
        if not self.config_exists():
            self.write_config()
        self.read_config()
        self.users_file_path = 'users'
        self.users = dict()
        if not self.users_file_exists():
            self.write_users()
        self.read_users()
        self.user_sessions = dict()  # пользовательские сессии

    def config_exists(self):
        try:
            open(self.config_file_path, "r")
        except FileNotFoundError:
            return False

        return True

    def read_config(self):
        logging.info("reading config from " + self.config_file_path)
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

    def users_file_exists(self):
        try:
            open(self.users_file_path, "r")
        except FileNotFoundError:
            return False

        return True

    def read_users(self):
        logging.info(f"reading users from '{self.users_file_path}'")
        data = None
        try:
            with open(self.users_file_path, "r") as read_file:
                data = json.load(read_file)
        except FileNotFoundError:
            logging.warning("Could not load user accounts: file not found")
            return False
        except JSONDecodeError as e:
            logging.error(e.msg)

        self.parse_users(data)

        return True

    def parse_users(self, data):
        try:
            for key, user in data['users'].items():
                login = user['login']
                fullname = user['full_name']
                passwdhash = user['password_hash']

                new_user = User(login, passwdhash)
                new_user.full_name = fullname
                self.users[login] = new_user
        except KeyError as e:
            logging.error(e)

        return True

    def write_users(self):
        data = dict()
        data["users"] = self.users

        with open(self.users_file_path, "w") as write_file:
            json.dump(data, write_file, default=custom_serializer)

        logging.info("users saved to file")

    def reset_admin_password(self, new_password: str):
        if not new_password:
            return

        password_hash = make_hash(new_password)

        admin = self.users.get('admin')
        if not admin:
            admin = User('admin', password_hash)
        else:
            admin.password_hash = password_hash
        self.users['admin'] = admin

    def check_user(self, login: str, auth_string: str) -> bool:
        if not login:
            logging.error(f"user login is empty")
            return False
        if not auth_string:
            logging.error(f"authorization string is empty for user {login}")
            return False
        user = self.users.get(login)
        if not user:
            logging.error(f"user account not found: {login}")
            return False
        lst = auth_string.splitlines()
        if (len(lst)) != 3:
            logging.error(f"invalid authorization data for user {login}")
            return False
        passw_hash = lst[2]
        if user.password_hash == passw_hash:
            return True
        return False

    def start_user_session(self, login: str):
        """ Начать новую сессию пользователя 'login', если она еще не существует """
        session = self.user_sessions.get(login)
        if not session:
            session = UserSession(login)
            self.user_sessions[login] = session
            logging.info(f"new session for user '{login}'")
            logging.info(f"active user sessions: {len(self.user_sessions)}")

    def on_new_command(self, text):
        self.parse_command(text)

    async def run_server(self):
        logging.info('running webserver')
        loop = asyncio.get_running_loop()
        self.stop_webserver = loop.create_future()
        async with websockets.serve(self.web_server.ws_handler, "192.168.0.195", 8001):
            await self.stop_webserver

    def administration_thread_func(self):
        ''' Управление пользовательскими сессиями и различные фоновые задачи '''
        logging.info('starting administration thread function')

        self.do_administration_thread = True

        while self.do_administration_thread:
            for user_login, user_session in list(self.user_sessions.items()):
                if user_session.expired():
                    logging.info(f'expired user session closed: {user_login}')
                    del self.user_sessions[user_login]
                    logging.info(f"active user sessions: {len(self.user_sessions)}")

            time.sleep(0.5)

        logging.info('administration thread function finished')

    def program_thread_func(self):
        ''' Управление отдельными заданиями и рабочей программой '''
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

        self.read_users()

        logging.info('starting administration thread...')
        self.administration_thread = threading.Thread(target=self.administration_thread_func)
        self.administration_thread.start()
        logging.info('done')

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
        self.administration_thread.join()

        logging.info('<- run')

    def set_light_intensity(self, value):
        if value < 0:
            value = 0
        if value > 100:
            value = 100
        self.main_light_intensity = value

    def decrypt(self, data):
        data_bytes = base64.b64decode(data)
        plaintext = self.web_server.private_key.decrypt(
            data_bytes,
            padding.OAEP(
                mgf=padding.MGF1(algorithm=hashes.SHA256()),
                algorithm=hashes.SHA256(),
                label=None
            )
        )

        return plaintext.decode('utf-8')

    def parse_command(self, text: str):
        #root = etree.fromstring(text)
        root = json.loads(text)

        #print(root.tag, root.attrib)
        encrypted = root["encrypted"]
        data = root["data"]

        if encrypted:
            data = self.decrypt(data)
        data = json.loads(data)

        opcode = data["opcode"]
        if not opcode:
            return

        # команды, не требующие наличия активной пользовательской сессии:
        stop_processing = True
        match opcode:
            case "hello":
                self.on_command_hello(data)
            case "handshakeReq":
                self.on_command_handshake_req(data)
            case "login":
                self.on_command_login(data)
            case _:
                stop_processing = False

        if stop_processing:
            return

        user_session = self.user_sessions.get(user_login)
        if user_session:
            user_session.refresh()
        else:
            logging.error(f"user not authorized: {user_login}")
            return

        # команды, выполняемые только в активной пользовательской сессии:
        match opcode:
            case "setLightIntensity":
                self.on_command_set_light_intensity(data)
            case "waterOn":
                self.on_command_water_on(data)
            case "waterOff":
                self.on_command_water_off(data)
            case "foggerPumpOn":
                self.on_command_fogger_pump_on(data)
            case "foggerPumpOff":
                self.on_command_fogger_pump_off(data)
            case "checkOnline":
                self.on_command_check_online(data)
            case "updateFromServer":
                self.on_command_update_from_server(data)
            case "serverShutdown":
                self.on_command_server_shutdown(data)
            case "setScriptMode":
                self.on_command_set_script_mode(data)
            case "setManualMode":
                self.on_command_set_manual_mode(data)
            case "getProgramList":
                self.on_command_get_program_list(data)
            case "doSunrise":
                self.on_command_do_sunrise(data)
            case "doSunset":
                self.on_command_do_sunset(data)
            case _:
                pass

    def on_command_hello(self, elem):
        logging.info("hello from client")
        cmd_text = self.make_command_hello_reply()
        cur_loop = asyncio.get_event_loop()
        asyncio.run_coroutine_threadsafe(self.web_server.send_to_client(cmd_text), cur_loop)

    def on_command_handshake_req(self, elem):
        logging.info("handshake request from client")
        cmd_text = self.make_command_handshake_ack()
        if not cmd_text:
            logging.warning("handshake request received, but reply was not generated, sending nothing to client")
            return
        cur_loop = asyncio.get_event_loop()
        asyncio.run_coroutine_threadsafe(self.web_server.send_to_client(cmd_text), cur_loop)

    def on_command_login(self, elem):
        if 'userLogin' not in elem:
            logging.error()
            return
        if 'authString' not in elem:
            logging.error("invalid (empty) login command")
            return
        user_login = elem['userLogin']
        auth_string = elem['authString']
        logging.info(f"user login: {user_login}")
        logging.info(f"login raw data: {auth_string}")

        is_ok = self.check_user(user_login, auth_string)
        if is_ok:
            logging.info(f"user authorization successful: {user_login}")
            self.start_user_session(user_login)
        else:
            logging.error(f"user authorization FAILED: {user_login}")

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

    def make_command_hello_reply(self):
        return json.dumps({'opcode': 'hello hello'})

    def make_command_handshake_ack(self):
        if not self.web_server.private_key:
            return None
        public_key = self.web_server.private_key.public_key()
        pem_string = public_key.public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo
        ).decode('utf-8')

        return json.dumps({'opcode': 'handshakeAck', 'key': pem_string})

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
        self.do_administration_thread = False
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
    parser = argparse.ArgumentParser(description="TerraCon server")
    parser.add_argument("-r", "--reset_admin", action='store_true',
                        help="Reset admin password"
                        )
    parser.add_argument("-p", "--new_password", help="New password for admin")

    args = parser.parse_args()

    logToFile = False
    loggingFormat = "[%(asctime)s : %(levelname)s] %(message)s"
    if logToFile:
        logging.basicConfig(level=logging.INFO, filename='terracon.log', filemode='a', format=loggingFormat)
    else:
        logging.basicConfig(level=logging.INFO, format=loggingFormat)
    logging.getLogger().setLevel(logging.INFO)

    logging.info("Program (re)started")

    worker = Worker(gpio_present)

    if args.reset_admin:
        if args.new_password:
            worker.reset_admin_password(args.new_password)
            worker.write_users()
            logging.info("Admin password has been chanded")
        else:
            logging.warning("Admin password change requested, but new password was not specified.")

    #signal.signal(signal.SIGINT, partial(handler_ctrl_c, worker))
    worker.run()

    logging.info("Exit")

main()

