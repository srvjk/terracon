import importlib
import importlib.util
from datetime import datetime


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

    def finish(self):
        self.is_done = True


class TerraconProgramEngine:
    def __init__(self):
        self.should_stop = False
        self.program = None
        self.tasks = list()
        self.root_task = None

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


def main():
    engine = TerraconProgramEngine()
    engine.run_program()

if __name__ == "__main__":
    main()

