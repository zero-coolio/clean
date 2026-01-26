#!/usr/bin/env python3
"""Debug script to test parsing functions."""
import sys
sys.path.insert(0, '.')

from src.utils import strip_noise_prefix, normalize_unicode_separators
from src.service.clean_movie_service import parse_movie_from_string, clean_movie_title
from src.service.clean_service import parse_episode_from_string


def test_prefix_stripping():
    """Test noise prefix stripping."""
    print("=== Prefix Stripping Tests ===")
    
    tests = [
        ("[YTS] The.Dark.Knight.2008.1080p", "The.Dark.Knight.2008.1080p"),
        ("rarbg-Interstellar.2014.2160p.UHD", "Interstellar.2014.2160p.UHD"),
        ("[rartv]Show.S01E01.720p", "Show.S01E01.720p"),
        ("www.site.org - Movie.2020.mkv", "Movie.2020.mkv"),
    ]
    
    for input_str, expected in tests:
        result = strip_noise_prefix(input_str)
        status = "✓" if result == expected else "✗"
        print(f"  {status} '{input_str}'")
        print(f"      -> '{result}'")
        if result != expected:
            print(f"      Expected: '{expected}'")
    print()


def test_movie_parsing():
    """Test movie parsing."""
    print("=== Movie Parsing Tests ===")
    
    tests = [
        ("The.Matrix.1999.1080p.BluRay.x264-GROUP", ("The Matrix", "1999")),
        ("The Matrix (1999)", ("The Matrix", "1999")),
        ("[YTS] The.Dark.Knight.2008.1080p", ("The Dark Knight", "2008")),
        ("rarbg-Interstellar.2014.2160p.UHD", ("Interstellar", "2014")),
        ("2001.A.Space.Odyssey.1968.1080p", ("2001 A Space Odyssey", "1968")),
        ("Die.Hard.2.1990.1080p.BluRay", ("Die Hard 2", "1990")),
    ]
    
    for input_str, expected in tests:
        result = parse_movie_from_string(input_str)
        status = "✓" if result == expected else "✗"
        print(f"  {status} '{input_str}'")
        print(f"      -> {result}")
        if result != expected:
            print(f"      Expected: {expected}")
    print()


def test_episode_parsing():
    """Test episode parsing."""
    print("=== Episode Parsing Tests ===")
    
    tests = [
        ("Letterkenny.S05E01.1080p.HULU.WEBRip.mkv", ("Letterkenny", "05", "01")),
        ("Show Name - 5x2 - Episode Title", ("Show Name", "05", "02")),
        ("[rartv]Show.S01E01.720p", ("Show", "01", "01")),
        ("show.name.s01e01.720p.mkv", ("Show Name", "01", "01")),
    ]
    
    for input_str, expected in tests:
        result = parse_episode_from_string(input_str)
        status = "✓" if result == expected else "✗"
        print(f"  {status} '{input_str}'")
        print(f"      -> {result}")
        if result != expected:
            print(f"      Expected: {expected}")
    print()


if __name__ == "__main__":
    test_prefix_stripping()
    test_movie_parsing()
    test_episode_parsing()
    print("Done!")
