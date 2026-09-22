import unittest
from queue import Queue
from unittest.mock import Mock
from rendering.manim.low_memory import ImmediateFrames, configure_encoder


class LowMemoryTests(unittest.TestCase):
    def test_x264_preserves_quality_and_limits_buffers(self):
        context = Mock(name="codec")
        context.name = "libx264"
        context.options = {"crf": "23"}
        configure_encoder(Mock(codec_context=context))
        self.assertEqual(context.thread_count, 1)
        self.assertEqual(context.options["crf"], "23")
        self.assertEqual(context.options["rc-lookahead"], "0")
        self.assertEqual(context.options["bf"], "0")

    def test_other_codecs_do_not_receive_x264_options(self):
        context = Mock()
        context.name = "qtrle"
        context.options = {}
        configure_encoder(Mock(codec_context=context))
        self.assertEqual(context.options, {})

    def test_frames_encode_immediately_and_sentinel_reaches_worker(self):
        queue, encode = Queue(), Mock()
        writer = ImmediateFrames(queue, encode)
        frame = object()
        writer.put((3, frame))
        encode.assert_called_once_with(frame, 3)
        self.assertTrue(queue.empty())
        writer.put((0, None))
        self.assertEqual(writer.get(), (0, None))

    def test_encoding_failure_reaches_caller(self):
        writer = ImmediateFrames(Queue(), Mock(side_effect=MemoryError()))
        with self.assertRaises(MemoryError):
            writer.put((1, object()))
