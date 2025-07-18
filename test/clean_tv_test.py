import unittest
import tempfile
import os
import shutil
from unittest.mock import patch
import logging
from io import StringIO

# Import the module under test
from src import Main


class TestParseTVFilename(unittest.TestCase):
    """Test cases for parse_tv_filename function"""

    def test_standard_format(self):
        """Test standard TV filename formats"""
        show, season, episode = Main.parse_tv_filename("The Office S01E01.mkv")
        self.assertEqual(show, "The Office")
        self.assertEqual(season, "01")
        self.assertEqual(episode, "01")

    def test_lowercase_format(self):
        """Test lowercase season/episode format"""
        show, season, episode = Main.parse_tv_filename("friends s02e15.avi")
        self.assertEqual(show, "friends")
        self.assertEqual(season, "02")
        self.assertEqual(episode, "15")

    def test_dots_in_show_name(self):
        """Test show names with dots replaced by spaces"""
        show, season, episode = Main.parse_tv_filename("The.Big.Bang.Theory.S03E22.mkv")
        self.assertEqual(show, "The Big Bang Theory")
        self.assertEqual(season, "03")
        self.assertEqual(episode, "22")

    def test_underscores_in_show_name(self):
        """Test show names with underscores replaced by spaces"""
        show, season, episode = Main.parse_tv_filename("Breaking_Bad_S05E14.mp4")
        self.assertEqual(show, "Breaking Bad")
        self.assertEqual(season, "05")
        self.assertEqual(episode, "14")

    def test_dashes_in_show_name(self):
        """Test show names with dashes replaced by spaces"""
        show, season, episode = Main.parse_tv_filename("Game-of-Thrones-S08E06.mkv")
        self.assertEqual(show, "Game of Thrones")
        self.assertEqual(season, "08")
        self.assertEqual(episode, "06")

    def test_mixed_separators(self):
        """Test show names with mixed separators"""
        show, season, episode = Main.parse_tv_filename("How.I_Met-Your Mother S09E24.mkv")
        self.assertEqual(show, "How I Met Your Mother")
        self.assertEqual(season, "09")
        self.assertEqual(episode, "24")

    def test_extra_info_after_episode(self):
        """Test filenames with extra info after episode number"""
        show, season, episode = Main.parse_tv_filename("Stranger Things S04E09 1080p BluRay x264.mkv")
        self.assertEqual(show, "Stranger Things")
        self.assertEqual(season, "04")
        self.assertEqual(episode, "09")

    def test_single_digit_season_episode(self):
        """Test single digit season and episode numbers"""
        show, season, episode = Main.parse_tv_filename("Lost S1E5.avi")
        self.assertEqual(show, "Lost")
        self.assertEqual(season, "01")
        self.assertEqual(episode, "05")

    def test_double_digit_season_episode(self):
        """Test double digit season and episode numbers"""
        show, season, episode = Main.parse_tv_filename("The Simpsons S12E25.mp4")
        self.assertEqual(show, "The Simpsons")
        self.assertEqual(season, "12")
        self.assertEqual(episode, "25")

    def test_multiple_spaces_in_show_name(self):
        """Test show names with multiple spaces normalized"""
        show, season, episode = Main.parse_tv_filename("Show   With    Spaces S01E01.mkv")
        self.assertEqual(show, "Show With Spaces")
        self.assertEqual(season, "01")
        self.assertEqual(episode, "01")

    def test_invalid_format_no_season_episode(self):
        """Test invalid filename without season/episode info"""
        show, season, episode = Main.parse_tv_filename("random_file.mkv")
        self.assertIsNone(show)
        self.assertIsNone(season)
        self.assertIsNone(episode)

    def test_invalid_format_incomplete_episode(self):
        """Test invalid filename with incomplete episode format"""
        show, season, episode = Main.parse_tv_filename("Show S01.mkv")
        self.assertIsNone(show)
        self.assertIsNone(season)
        self.assertIsNone(episode)

    def test_empty_filename(self):
        """Test empty filename"""
        show, season, episode = Main.parse_tv_filename("")
        self.assertIsNone(show)
        self.assertIsNone(season)
        self.assertIsNone(episode)

    def test_subtitle_file_format(self):
        """Test subtitle file format"""
        show, season, episode = Main.parse_tv_filename("The Office S01E01.srt")
        self.assertEqual(show, "The Office")
        self.assertEqual(season, "01")
        self.assertEqual(episode, "01")


class TestProcessFile(unittest.TestCase):
    """Test cases for process_file function"""

    def setUp(self):
        """Set up test fixtures"""
        self.temp_dir = tempfile.mkdtemp()
        self.intake_root = self.temp_dir

        # Capture log output
        self.log_capture = StringIO()
        self.handler = logging.StreamHandler(self.log_capture)
        Main.logger.addHandler(self.handler)
        Main.logger.setLevel(logging.INFO)

    def tearDown(self):
        """Clean up test fixtures"""
        shutil.rmtree(self.temp_dir)
        Main.logger.removeHandler(self.handler)

    def test_delete_sample_file(self):
        """Test deletion of sample files"""
        sample_file = os.path.join(self.temp_dir, "sample.mkv")
        with open(sample_file, 'w') as f:
            f.write("test")

        Main.process_file(sample_file, self.intake_root, dry_run=False)

        self.assertFalse(os.path.exists(sample_file))
        self.assertIn("DELETE SAMPLE FILE", self.log_capture.getvalue())

    def test_delete_sample_file_dry_run(self):
        """Test sample file deletion in dry run mode"""
        sample_file = os.path.join(self.temp_dir, "SAMPLE_video.mkv")
        with open(sample_file, 'w') as f:
            f.write("test")

        Main.process_file(sample_file, self.intake_root, dry_run=True)

        self.assertTrue(os.path.exists(sample_file))
        self.assertIn("DELETE SAMPLE FILE", self.log_capture.getvalue())

    def test_delete_auxiliary_files(self):
        """Test deletion of auxiliary files"""
        aux_files = ['test.nfo', 'test.txt', 'test.jpg', 'test.png', '.ds_store']

        for filename in aux_files:
            file_path = os.path.join(self.temp_dir, filename)
            with open(file_path, 'w') as f:
                f.write("test")

            Main.process_file(file_path, self.intake_root, dry_run=False)

            self.assertFalse(os.path.exists(file_path))
            self.assertIn("DELETE AUXILIARY FILE", self.log_capture.getvalue())

    def test_move_tv_file(self):
        """Test moving a properly formatted TV file"""
        source_file = os.path.join(self.temp_dir, "The Office S01E01.mkv")
        with open(source_file, 'w') as f:
            f.write("test content")

        Main.process_file(source_file, self.intake_root, dry_run=False)

        expected_path = os.path.join(self.intake_root, "The Office", "Season 01", "The Office S01E01.mkv")
        self.assertTrue(os.path.exists(expected_path))
        self.assertFalse(os.path.exists(source_file))
        self.assertIn("MOVE:", self.log_capture.getvalue())

    def test_move_tv_file_dry_run(self):
        """Test moving TV file in dry run mode"""
        source_file = os.path.join(self.temp_dir, "Friends S02E05.mp4")
        with open(source_file, 'w') as f:
            f.write("test content")

        Main.process_file(source_file, self.intake_root, dry_run=True)

        expected_path = os.path.join(self.intake_root, "Friends", "Season 02", "Friends S02E05.mp4")
        self.assertFalse(os.path.exists(expected_path))
        self.assertTrue(os.path.exists(source_file))
        self.assertIn("MOVE:", self.log_capture.getvalue())

    def test_skip_unparseable_file(self):
        """Test skipping files that can't be parsed"""
        unparseable_file = os.path.join(self.temp_dir, "random_video.mkv")
        with open(unparseable_file, 'w') as f:
            f.write("test")

        Main.process_file(unparseable_file, self.intake_root, dry_run=False)

        self.assertTrue(os.path.exists(unparseable_file))
        self.assertIn("SKIPPED: Could not parse TV file", self.log_capture.getvalue())

    def test_skip_already_correctly_placed(self):
        """Test skipping files already in correct location"""
        show_dir = os.path.join(self.intake_root, "The Office", "Season 01")
        os.makedirs(show_dir, exist_ok=True)

        correct_file = os.path.join(show_dir, "The Office S01E01.mkv")
        with open(correct_file, 'w') as f:
            f.write("test")

        Main.process_file(correct_file, self.intake_root, dry_run=False)

        # File should still exist in same location
        self.assertTrue(os.path.exists(correct_file))
        self.assertIn("SKIPPED: Already correctly placed", self.log_capture.getvalue())

    def test_skip_destination_exists(self):
        """Test skipping when destination file already exists"""
        # Create source file
        source_file = os.path.join(self.temp_dir, "The Office S01E01.mkv")
        with open(source_file, 'w') as f:
            f.write("source content")

        # Create existing destination file
        dest_dir = os.path.join(self.intake_root, "The Office", "Season 01")
        os.makedirs(dest_dir, exist_ok=True)
        dest_file = os.path.join(dest_dir, "The Office S01E01.mkv")
        with open(dest_file, 'w') as f:
            f.write("existing content")

        Main.process_file(source_file, self.intake_root, dry_run=False)

        # Both files should exist
        self.assertTrue(os.path.exists(source_file))
        self.assertTrue(os.path.exists(dest_file))
        self.assertIn("SKIPPED: Destination file already exists", self.log_capture.getvalue())

    def test_filename_normalization(self):
        """Test filename normalization during move"""
        source_file = os.path.join(self.temp_dir, "The.Big.Bang.Theory.S03E15.1080p.BluRay.mkv")
        with open(source_file, 'w') as f:
            f.write("test")

        Main.process_file(source_file, self.intake_root, dry_run=False)

        expected_path = os.path.join(
            self.intake_root,
            "The Big Bang Theory",
            "Season 03",
            "The Big Bang Theory S03E15.1080p.BluRay.mkv"
        )
        self.assertTrue(os.path.exists(expected_path))


class TestProcessSidecarFiles(unittest.TestCase):
    """Test cases for process_sidecar_files function"""

    def setUp(self):
        """Set up test fixtures"""
        self.temp_dir = tempfile.mkdtemp()
        self.intake_root = self.temp_dir

        # Capture log output
        self.log_capture = StringIO()
        self.handler = logging.StreamHandler(self.log_capture)
        Main.logger.addHandler(self.handler)
        Main.logger.setLevel(logging.INFO)

    def tearDown(self):
        """Clean up test fixtures"""
        shutil.rmtree(self.temp_dir)
        Main.logger.removeHandler(self.handler)

    def test_move_subtitle_files(self):
        """Test moving subtitle files to correct locations"""
        # Create a subtitle file in wrong location
        random_dir = os.path.join(self.temp_dir, "random_folder")
        os.makedirs(random_dir)

        srt_file = os.path.join(random_dir, "The Office S01E01.srt")
        with open(srt_file, 'w') as f:
            f.write("subtitle content")

        Main.process_sidecar_files(self.intake_root, dry_run=False)

        expected_path = os.path.join(
            self.intake_root,
            "The Office",
            "Season 01",
            "The Office S01E01.srt"
        )
        self.assertTrue(os.path.exists(expected_path))
        self.assertFalse(os.path.exists(srt_file))
        self.assertIn("MOVE SIDECAR:", self.log_capture.getvalue())

    def test_move_subtitle_files_dry_run(self):
        """Test moving subtitle files in dry run mode"""
        random_dir = os.path.join(self.temp_dir, "random_folder")
        os.makedirs(random_dir)

        srt_file = os.path.join(random_dir, "Friends S02E10.srt")
        with open(srt_file, 'w') as f:
            f.write("subtitle content")

        Main.process_sidecar_files(self.intake_root, dry_run=True)

        expected_path = os.path.join(
            self.intake_root,
            "Friends",
            "Season 02",
            "Friends S02E10.srt"
        )
        self.assertFalse(os.path.exists(expected_path))
        self.assertTrue(os.path.exists(srt_file))
        self.assertIn("MOVE SIDECAR:", self.log_capture.getvalue())

    def test_skip_unparseable_subtitle_files(self):
        """Test skipping subtitle files that can't be parsed"""
        random_dir = os.path.join(self.temp_dir, "random_folder")
        os.makedirs(random_dir)

        srt_file = os.path.join(random_dir, "random_subtitle.srt")
        with open(srt_file, 'w') as f:
            f.write("subtitle content")

        Main.process_sidecar_files(self.intake_root, dry_run=False)

        # File should remain in original location
        self.assertTrue(os.path.exists(srt_file))
        # Should not log any move operation
        self.assertNotIn("MOVE SIDECAR:", self.log_capture.getvalue())


class TestCleanupEmptyDirs(unittest.TestCase):
    """Test cases for cleanup_empty_dirs function"""

    def setUp(self):
        """Set up test fixtures"""
        self.temp_dir = tempfile.mkdtemp()

        # Capture log output
        self.log_capture = StringIO()
        self.handler = logging.StreamHandler(self.log_capture)
        Main.logger.addHandler(self.handler)
        Main.logger.setLevel(logging.INFO)

    def tearDown(self):
        """Clean up test fixtures"""
        shutil.rmtree(self.temp_dir)
        Main.logger.removeHandler(self.handler)

    def test_remove_empty_directories(self):
        """Test removal of empty directories"""
        empty_dir = os.path.join(self.temp_dir, "empty_folder")
        os.makedirs(empty_dir)

        Main.cleanup_empty_dirs(self.temp_dir, dry_run=False)

        self.assertFalse(os.path.exists(empty_dir))
        self.assertIn("DELETE EMPTY DIR", self.log_capture.getvalue())

    def test_remove_empty_directories_dry_run(self):
        """Test removal of empty directories in dry run mode"""
        empty_dir = os.path.join(self.temp_dir, "empty_folder")
        os.makedirs(empty_dir)

        Main.cleanup_empty_dirs(self.temp_dir, dry_run=True)

        self.assertTrue(os.path.exists(empty_dir))
        self.assertIn("DELETE EMPTY DIR", self.log_capture.getvalue())

    def test_keep_directories_with_files(self):
        """Test keeping directories that contain files"""
        dir_with_file = os.path.join(self.temp_dir, "folder_with_file")
        os.makedirs(dir_with_file)

        test_file = os.path.join(dir_with_file, "test.txt")
        with open(test_file, 'w') as f:
            f.write("content")

        Main.cleanup_empty_dirs(self.temp_dir, dry_run=False)

        self.assertTrue(os.path.exists(dir_with_file))
        self.assertTrue(os.path.exists(test_file))
        self.assertNotIn("DELETE EMPTY DIR", self.log_capture.getvalue())

    def test_keep_directories_with_subdirs(self):
        """Test keeping directories that contain subdirectories"""
        parent_dir = os.path.join(self.temp_dir, "parent")
        child_dir = os.path.join(parent_dir, "child")
        os.makedirs(child_dir)

        # Add file to child directory
        test_file = os.path.join(child_dir, "test.txt")
        with open(test_file, 'w') as f:
            f.write("content")

        Main.cleanup_empty_dirs(self.temp_dir, dry_run=False)

        self.assertTrue(os.path.exists(parent_dir))
        self.assertTrue(os.path.exists(child_dir))
        self.assertTrue(os.path.exists(test_file))

    def test_ignore_hidden_files_and_dirs(self):
        """Test that hidden files and directories don't prevent cleanup"""
        dir_with_hidden = os.path.join(self.temp_dir, "folder_with_hidden")
        os.makedirs(dir_with_hidden)

        # Create hidden file and directory
        hidden_file = os.path.join(dir_with_hidden, ".hidden_file")
        hidden_dir = os.path.join(dir_with_hidden, ".hidden_dir")

        with open(hidden_file, 'w') as f:
            f.write("hidden content")
        os.makedirs(hidden_dir)

        Main.cleanup_empty_dirs(self.temp_dir, dry_run=False)

        # Directory should be removed despite hidden files/dirs
        self.assertFalse(os.path.exists(dir_with_hidden))

    def test_nested_empty_directories(self):
        """Test removal of nested empty directories"""
        level1 = os.path.join(self.temp_dir, "level1")
        level2 = os.path.join(level1, "level2")
        level3 = os.path.join(level2, "level3")
        os.makedirs(level3)

        Main.cleanup_empty_dirs(self.temp_dir, dry_run=False)

        # All levels should be removed
        self.assertFalse(os.path.exists(level1))
        self.assertFalse(os.path.exists(level2))
        self.assertFalse(os.path.exists(level3))


class TestMainFunction(unittest.TestCase):
    """Test cases for main function and argument parsing"""

    @patch('Main.os.walk')
    @patch('Main.process_file')
    @patch('Main.process_sidecar_files')
    @patch('Main.cleanup_empty_dirs')
    @patch('sys.argv', ['Main.py', '--directory', '/test/path'])
    def test_main_function_normal_run(self, mock_cleanup, mock_sidecar, mock_process, mock_walk):
        """Test main function normal execution"""
        # Mock os.walk to return test data
        mock_walk.return_value = [
            ('/test/path', ['subdir'], ['test.mkv', 'sample.avi', 'readme.txt'])
        ]

        Main.main()

        # Verify all processing functions are called
        mock_process.assert_called()
        mock_sidecar.assert_called_once()
        mock_cleanup.assert_called_once()

    @patch('Main.os.walk')
    @patch('Main.process_file')
    @patch('Main.process_sidecar_files')
    @patch('Main.cleanup_empty_dirs')
    @patch('sys.argv', ['Main.py', '--directory', '/test/path', '--dry-run'])
    def test_main_function_dry_run(self, mock_cleanup, mock_sidecar, mock_process, mock_walk):
        """Test main function with dry run flag"""
        mock_walk.return_value = [
            ('/test/path', [], ['test.mkv'])
        ]

        Main.main()

        # Verify dry_run=True is passed to functions
        mock_process.assert_called_with(
            '/test/path/test.mkv',
            os.path.abspath('/test/path'),
            True
        )
        mock_sidecar.assert_called_with(os.path.abspath('/test/path'), True)
        mock_cleanup.assert_called_with(os.path.abspath('/test/path'), True)

    def test_file_extension_filtering(self):
        """Test that only appropriate file extensions are processed"""
        with tempfile.TemporaryDirectory() as temp_dir:
            # Create files with various extensions
            test_files = [
                'video.mkv',  # Should process
                'video.mp4',  # Should process
                'video.avi',  # Should process
                'video.mov',  # Should process
                'info.nfo',  # Should process (for deletion)
                'readme.txt',  # Should process (for deletion)
                'thumb.jpg',  # Should process (for deletion)
                'poster.png',  # Should process (for deletion)
                '.DS_Store',  # Should process (for deletion)
                'ignore.xyz',  # Should NOT process
                'document.pdf',  # Should NOT process
            ]

            for filename in test_files:
                with open(os.path.join(temp_dir, filename), 'w') as f:
                    f.write("test")

            with patch('Main.process_file') as mock_process:
                with patch('sys.argv', ['Main.py', '--directory', temp_dir]):
                    Main.main()

                # Check which files were processed
                processed_files = [call[0][0] for call in mock_process.call_args_list]
                processed_basenames = [os.path.basename(f) for f in processed_files]

                # Should process video and auxiliary files
                expected_processed = [
                    'video.mkv', 'video.mp4', 'video.avi', 'video.mov',
                    'info.nfo', 'readme.txt', 'thumb.jpg', 'poster.png', '.DS_Store'
                ]

                for expected in expected_processed:
                    self.assertIn(expected, processed_basenames)

                # Should not process other files
                self.assertNotIn('ignore.xyz', processed_basenames)
                self.assertNotIn('document.pdf', processed_basenames)


class TestLogging(unittest.TestCase):
    """Test cases for logging functionality"""

    def setUp(self):
        """Set up test fixtures"""
        self.log_capture = StringIO()
        self.handler = logging.StreamHandler(self.log_capture)
        Main.logger.addHandler(self.handler)
        Main.logger.setLevel(logging.INFO)

    def tearDown(self):
        """Clean up test fixtures"""
        Main.logger.removeHandler(self.handler)

    def test_logger_configuration(self):
        """Test that logger is properly configured"""
        self.assertEqual(Main.logger.name, "tv_processor")
        self.assertEqual(Main.logger.level, logging.INFO)

    def test_logging_messages(self):
        """Test that various log messages are generated correctly"""
        Main.logger.info("Test info message")
        Main.logger.warning("Test warning message")

        log_output = self.log_capture.getvalue()
        self.assertIn("Test info message", log_output)
        self.assertIn("Test warning message", log_output)


if __name__ == '__main__':
    # Create a test suite
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()

    # Add all test classes
    test_classes = [
        TestParseTVFilename,
        TestProcessFile,
        TestProcessSidecarFiles,
        TestCleanupEmptyDirs,
        TestMainFunction,
        TestLogging
    ]

    for test_class in test_classes:
        tests = loader.loadTestsFromTestCase(test_class)
        suite.addTests(tests)

    # Run the tests
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    # Print summary
    print(f"\n{'=' * 60}")
    print(f"Tests run: {result.testsRun}")
    print(f"Failures: {len(result.failures)}")
    print(f"Errors: {len(result.errors)}")
    print(
        f"Success rate: {((result.testsRun - len(result.failures) - len(result.errors)) / result.testsRun * 100):.1f}%")
    print(f"{'=' * 60}")