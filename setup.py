from setuptools import setup, find_packages
import terracon

setup(
	name='terracon',
	version=terracon.__version__,
	packages=find_packages(),
	install_requires=[],
	entry_points={
		'console_scripts':
			['terracon = terracon.terracon:main']
		}
)
