import unittest
from unittest import mock

import numpy as np

import pitchlens.core.audio as audio
from pitchlens.core.audio import AudioRingBuffer


class AudioTests(unittest.TestCase):
    def test_ring_buffer_wrap(self):
        buffer = AudioRingBuffer(capacity=10)
        buffer.write(np.arange(6, dtype=np.float32))
        data = buffer.read_last(4)
        np.testing.assert_array_equal(data, np.array([2, 3, 4, 5], dtype=np.float32))
        buffer.write(np.arange(6, 12, dtype=np.float32))
        data = buffer.read_last(6)
        np.testing.assert_array_equal(data, np.array([6, 7, 8, 9, 10, 11], dtype=np.float32))
        self.assertIsNone(buffer.read_last(11))

    def test_ring_buffer_large_write(self):
        buffer = AudioRingBuffer(capacity=5)
        buffer.write(np.arange(12, dtype=np.float32))
        np.testing.assert_array_equal(
            buffer.read_last(5), np.array([7, 8, 9, 10, 11], dtype=np.float32)
        )

    def test_device_list_filters_wdm_ks_garbage(self):
        devices = [
            {"name": "麦克风 (Realtek)", "max_input_channels": 2, "hostapi": 0,
             "default_samplerate": 48000},
            # WDM-KS pseudo device with a driver path as its name
            {"name": "耳机 (C:\\Windows\\System32\\drivers\\foo.sys)",
             "max_input_channels": 2, "hostapi": 2, "default_samplerate": 48000},
            {"name": "麦克风阵列", "max_input_channels": 0, "hostapi": 0,
             "default_samplerate": 48000},  # no input channels
            {"name": "线路输入", "max_input_channels": 2, "hostapi": 1,
             "default_samplerate": 44100},
        ]
        hostapis = [
            {"name": "MME"},
            {"name": "Windows DirectSound"},
            {"name": "Windows WDM-KS"},
        ]
        with mock.patch.object(audio.sd, "query_devices", return_value=devices), \
             mock.patch.object(audio.sd, "query_hostapis", return_value=hostapis), \
             mock.patch.object(audio.sd, "default") as default:
            default.device = [0, 1]
            found = audio.list_input_devices()
        names = [d.name for d in found]
        self.assertEqual(names, ["麦克风 (Realtek)", "线路输入"])
        self.assertTrue(found[0].is_default)

    def test_device_list_dedupes_host_apis(self):
        # The same physical mic under MME / DirectSound / WASAPI (WASAPI name
        # often truncated) collapses to one entry — the WASAPI one.
        devices = [
            {"name": "麦克风 (Realtek High Definition Audio)",
             "max_input_channels": 2, "hostapi": 0, "default_samplerate": 48000},
            {"name": "麦克风 (Realtek High Definition Audio)",
             "max_input_channels": 2, "hostapi": 1, "default_samplerate": 48000},
            {"name": "麦克风 (Realtek High Definition Au",
             "max_input_channels": 2, "hostapi": 3, "default_samplerate": 48000},
            {"name": "立体声混音 (Realtek)", "max_input_channels": 2,
             "hostapi": 0, "default_samplerate": 48000},
        ]
        hostapis = [
            {"name": "MME"},
            {"name": "Windows DirectSound"},
            {"name": "Windows WDM-KS"},
            {"name": "Windows WASAPI"},
        ]
        with mock.patch.object(audio.sd, "query_devices", return_value=devices), \
             mock.patch.object(audio.sd, "query_hostapis", return_value=hostapis), \
             mock.patch.object(audio.sd, "default") as default:
            default.device = [0, 1]
            found = audio.list_input_devices()
        self.assertEqual(len(found), 2)
        # WASAPI entry survives the dedupe, and keeps the default flag.
        mic = next(d for d in found if "High Definition" in d.name or "Au" in d.name)
        self.assertEqual(mic.hostapi, "Windows WASAPI")
        self.assertEqual(mic.index, 2)
        self.assertTrue(mic.is_default)
        self.assertTrue(found[0].is_default)  # default sorted first


if __name__ == "__main__":
    unittest.main()
