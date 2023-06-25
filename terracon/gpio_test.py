#!/usr/bin/python3

import RPi.GPIO as GPIO
import time

def run_gpio_simple():
    print('running gpio')

    GPIO.setmode(GPIO.BCM)    # устанавливаем режим нумерации по назв. каналов
    GPIO.setup(12, GPIO.OUT)  # назначаем пин GPIO12 выходным
    pwm = GPIO.PWM(12, 20000)  # устанавливаем частоту ШИМ 20 кГц

    pwm.start(0)

    input("Press Enter...")
    intensity = 1
    print("Intensity: {}".format(intensity))
    pwm.ChangeDutyCycle(intensity)

    input("Press Enter...")
    intensity = 10
    print("Intensity: {}".format(intensity))
    pwm.ChangeDutyCycle(intensity)

    input("Press Enter...")
    intensity = 50
    print("Intensity: {}".format(intensity))
    pwm.ChangeDutyCycle(intensity)

    input("Press Enter...")
    intensity = 100
    print("Intensity: {}".format(intensity))
    pwm.ChangeDutyCycle(intensity)

    input("Done. Press Enter to exit...")

    pwm.stop()

    GPIO.cleanup()

    print('gpio finished')


def run_gpio_cyclic():
    print('running gpio')

    GPIO.setmode(GPIO.BCM)    # устанавливаем режим нумерации по назв. каналов
    GPIO.setup(12, GPIO.OUT)  # назначаем пин GPIO12 выходным
    pwm = GPIO.PWM(12, 20000)  # устанавливаем частоту ШИМ 20 кГц

    pwm.start(0)

    n_cycles = 3
    min_intensity = 1
    max_intensity = 100
    step = 1
    time_delay = 0.1

    for cycle in range(n_cycles):
        intensity = 0
        while intensity < max_intensity:
            pwm.ChangeDutyCycle(intensity)
            time.sleep(time_delay)
            intensity += step

        intensity = max_intensity
        while intensity > min_intensity:
            pwm.ChangeDutyCycle(intensity)
            time.sleep(time_delay)
            intensity -= step

    pwm.stop()

    GPIO.cleanup()

    print('gpio finished')

def run_gpio_relay():
    print('running gpio relay test')

    GPIO.setmode(GPIO.BCM)    # устанавливаем режим нумерации по назв. каналов
    GPIO.setup(16, GPIO.OUT)  # назначаем пин GPIO16 выходным

    GPIO.output(16, GPIO.HIGH)

    input("Press Enter to START...")
    GPIO.output(16, GPIO.LOW)

    input("Press Enter to STOP...")
    GPIO.output(16, GPIO.HIGH)

    GPIO.cleanup()

    print('gpio relay test finished')


def main():
    run_gpio_relay()

main()

print("exit")
