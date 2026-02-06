#!/usr/bin/env python3
"""Diagnostic script: list audio devices and listen for Porcupine wakeword.

Run this with the project's venv active. It prints devices, then starts
listening and prints a message when the wake word is detected.
"""
import os
import sys
import time
try:
    import pvporcupine
except Exception as e:
    print("pvporcupine import failed:", e)
    sys.exit(2)
try:
    import pyaudio
except Exception as e:
    print("pyaudio import failed:", e)
    sys.exit(2)
import struct

def list_devices(pa):
    print("Available audio devices:")
    for i in range(pa.get_device_count()):
        info = pa.get_device_info_by_index(i)
        print(f"  {i}: {info.get('name')}  maxInputChannels={info.get('maxInputChannels')}")

def main():
    key = os.getenv('PORCUPINE_ACCESS_KEY') or None
    ppn_path = os.path.join(os.path.dirname(__file__), '..', 'models', 'ultron_win.ppn')
    ppn_path = os.path.normpath(ppn_path)
    use_custom = os.path.exists(ppn_path)

    try:
        if use_custom:
            print('Using custom model:', ppn_path)
            porcupine = pvporcupine.create(access_key=key, keyword_paths=[ppn_path])
        else:
            print('Using builtin keyword: porcupine')
            porcupine = pvporcupine.create(access_key=key, keywords=['porcupine'])
    except Exception as e:
        print('Failed creating Porcupine:', repr(e))
        sys.exit(2)

    pa = pyaudio.PyAudio()
    list_devices(pa)

    mic_index = None
    env_mi = os.getenv('MIC_INDEX')
    if env_mi:
        try:
            mi = int(env_mi)
            if mi >= 0:
                mic_index = mi
        except Exception:
            pass

    print('\nListening now. Speak the wake word clearly into the microphone.')
    if mic_index is not None:
        print('Using input device index:', mic_index)

    stream = None
    try:
        stream = pa.open(
            rate=porcupine.sample_rate,
            channels=1,
            format=pyaudio.paInt16,
            input=True,
            frames_per_buffer=porcupine.frame_length,
            input_device_index=mic_index,
        )
    except Exception as e:
        print('Failed to open audio stream:', e)
        porcupine.delete()
        pa.terminate()
        sys.exit(2)

    try:
        while True:
            pcm = stream.read(porcupine.frame_length, exception_on_overflow=False)
            pcm_unpacked = struct.unpack_from("%dh" % porcupine.frame_length, pcm)
            result = porcupine.process(pcm_unpacked)
            if result >= 0:
                print('WAKEWORD DETECTED! index=', result, 'time=', time.strftime('%Y-%m-%d %H:%M:%S'))
                break
    except KeyboardInterrupt:
        print('\nInterrupted by user')
    except Exception as e:
        print('Error while listening:', repr(e))
    finally:
        try:
            stream.stop_stream()
            stream.close()
        except Exception:
            pass
        porcupine.delete()
        pa.terminate()

if __name__ == '__main__':
    main()
