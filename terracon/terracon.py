#!/usr/bin/python3

import sys
from PyQt5 import QtWidgets


class TerraconWindow(QtWidgets.QWidget):
	def __init__(self):
		super().__init__()
		self.setWindowTitle('TerraCon')
		self.mainLayout = QtWidgets.QVBoxLayout()
		self.setLayout(self.mainLayout)
		self.exitButton = QtWidgets.QPushButton('Exit')
		self.mainLayout.addWidget(self.exitButton)
		self.exitButton.clicked.connect(QtWidgets.QApplication.quit)


def main():
	app = QtWidgets.QApplication(sys.argv)

	mainwnd = TerraconWindow()
	#w.resize(250, 150)
	#w.move(300, 300)
	#mainwnd.setWindowTitle('TerraCon')
	mainwnd.show()

	sys.exit(app.exec())


if __name__ == '__main__':
	main()

