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


def run_gpio_simple_type2():
    print('running gpio (second controller type)')

    GPIO.setmode(GPIO.BCM)    # устанавливаем режим нумерации по назв. каналов

    GPIO.setup(5, GPIO.OUT)  # назначаем пин GPIO12 выходным (управление светом)
    GPIO.setup(6, GPIO.OUT)  # назначаем пин GPIO12 выходным (управление светом)
    GPIO.setup(12, GPIO.OUT)  # назначаем пин GPIO12 выходным (управление светом)
    GPIO.setup(21, GPIO.OUT)  # назначаем пин GPIO12 выходным (управление светом)

    GPIO.setup(16, GPIO.OUT)  # назначаем пин GPIO16 выходным (управление водяной помпой)

    pwm = GPIO.PWM(12, 1000)  # устанавливаем частоту ШИМ 20 кГц

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


def run_gpio_simple_type3():
    print('running gpio')

    GPIO.setmode(GPIO.BCM)    # устанавливаем режим нумерации по назв. каналов
    GPIO.setup(12, GPIO.OUT)  # назначаем пин GPIO12 выходным
    pwm = GPIO.PWM(12, 1)

    pwm.start(0)

    input("Press Enter...")
    time.sleep(5)

    '''freqs = [100, 200, 2000, 5000, 10000]
    dcs = [1, 5, 10, 20]
    for f in freqs:
        pwm.ChangeFrequency(f)
        for dc in dcs:
            print('freq: {}, duty cycle: {}'.format(f, dc))
            pwm.ChangeDutyCycle(dc)
            time.sleep(1)'''

    min_freq = 100.0
    max_freq = 20000.0
    min_dc = 1.0
    max_dc = 100.0
    n = 1000
    df = float(max_freq - min_freq) / float(n)
    ddc = float(max_dc - min_dc) / float(n)
    f = min_freq
    dc = min_dc
    for i in range(1, n):
        pwm.ChangeFrequency(int(f))
        pwm.ChangeDutyCycle(int(dc))
        time.sleep(0.05)
        f += df
        dc += ddc

    '''for f in range(1, 20000, 100):
        print('freq: {}'.format(f))
        for dc in range(0, 100, 5):
            pwm.ChangeFrequency(f)
            pwm.ChangeDutyCycle(dc)
            time.sleep(0.1)'''

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
    run_gpio_simple_type3()

main()

print("exit")
