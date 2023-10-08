#from terracon import TerraconProgramEngine, Task
from datetime import time
import logging

class RootTask(Task):
    def __init__(self, name):
        super().__init__(name)
        logging.info('root task init')
        self.light_intensity = 0
        self.min_light_intensity = 1
        self.max_light_intensity = 99

    def step(self, engine):
        # если в списке заданий не найден LightingManager, создаем его
        lm = engine.find_task("LightingManager")
        if not lm:
            #logging.info("creating lighting manager")
            engine.new_task(LightingManager)

    def apply(self, engine):
        engine.worker.main_light_intensity = self.light_intensity


class LightingManager(Task):
    def __init__(self, name):
        super().__init__(name)
        logging.info('lighting manager init')
        self.start_time = time.fromisoformat('07:30:00')
        self.end_time = time.fromisoformat('23:59:00')

    def step(self, engine: TerraconProgramEngine):
        t = engine.current_time()
        if self.start_time < t < self.end_time:
            if self.root.light_intensity <= self.root.min_light_intensity:
                engine.new_task(Sunrise)
        else:
            if self.root.light_intensity >= self.root.max_light_intensity:
                engine.new_task(Sunset)

class Sunrise(Task):
    def __init__(self, name):
        super().__init__(name)
        self.duration = 5  # в секундах
        self.k = 0

    def step(self, engine):
        if self.k == 0:
            self.k = (self.root.max_light_intensity - self.root.min_light_intensity) / self.duration

        li = self.k * self.time_from_start_sec()
        if li > self.root.max_light_intensity:
            li = self.root.max_light_intensity

        self.root.light_intensity = li
        print("light: {}".format(self.root.light_intensity))
        if self.root.light_intensity >= self.root.max_light_intensity:
            print("Sunrise: light at max, finishing")
            self.finish()
        self.root.apply(engine)

class Sunset(Task):
    def __init__(self, name):
        super().__init__(name)

    def step(self, engine):
        self.root.light_intensity -= 1
        if self.root.light_intensity <= self.min_light_intensity:
            print("Sunset: light at min, finishing")
            self.finish()
        self.root.apply(engine)

def program_main(engine):
    print('executing program main function')
    engine.root_task = RootTask("root")
    engine.tasks.append(engine.root_task)
    print(engine)
    print(engine.tasks)
    print('done!')

program_main(engine)