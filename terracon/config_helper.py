import tomlkit
import os

class TOMLHelper():
    def __init__(self):
        super().__init__()
        self.data = None
        self.filepath = ""

    def create_empty_config(self):
        data = tomlkit.document()
        data.add(tomlkit.comment("TerraCon config file."))

        content = tomlkit.dumps(data)
        f = open(self.filepath, 'w')
        if not f:
            return
        f.write(content)
        f.close()

    def load(self, filepath):
        self.filepath = filepath
        if not os.path.isfile(self.filepath):
            self.create_empty_config()

        f = open(self.filepath, 'r')
        if not f:
            return

        content = f.read()
        self.data = tomlkit.parse(content)

        f.close()

    def save(self):
        f = open(self.filepath, 'w')
        if not f:
            return

        content = tomlkit.dumps(self.data)
        f.write(content)
        f.close()

