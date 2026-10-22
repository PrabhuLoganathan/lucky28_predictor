"""Shared repetition facts for the analysis table and rolling-window alerts."""
from collections import Counter

WINDOW_SIZE = 10


def summarize_window(numbers):
    numbers = [int(number) for number in numbers]
    counts = Counter(numbers)
    repeated = [dict(number=number, count=count) for number, count in counts.most_common() if count > 1]
    return dict(numbers=numbers, unique_count=len(counts), has_repetition=bool(repeated),
                repeated=repeated,
                repeated_details=', '.join(f'{item["number"]}x{item["count"]}' for item in repeated),
                newest_repeats=bool(numbers) and numbers[-1] in numbers[:-1])
