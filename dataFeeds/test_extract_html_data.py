import csv
import io
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from dataFeeds.extract_html_data import extract_data


def history_row(time='01:03', result='19', winners='467', prizes='37,006K'):
    return f"""<div class='van-cell-group van-hairline--top-bottom'>
        <div class='time_samll time' data-v-123=''>{time}</div>
        <div class='flex jc-c result' data-v-123=''>{result}</div>
        <div class='winners table_num'><img src='icon123.png'> {winners}</div>
        <div class='prizes table_num'><img src='icon456.png'> {prizes}
            <i class='arrow'><!----></i></div>
    </div>"""


class ExtractDataTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.input_file = Path(self.directory.name) / 'history.html'
        self.output_file = Path(self.directory.name) / 'history.csv'

    def extract(self, html, date_prefix='2026-09-06'):
        self.input_file.write_text(html, encoding='utf-8')
        with redirect_stdout(io.StringIO()):
            extract_data(self.input_file, self.output_file, date_prefix)
        with self.output_file.open(newline='', encoding='utf-8') as csvfile:
            return list(csv.DictReader(csvfile))

    def test_current_markup_excludes_headers_and_keeps_fields_together(self):
        header = """<div class='table_head'><div class='time'>Time</div>
            <div class='result'>Result</div><div class='winners'>Winners</div>
            <div class='prizes'>Prizes</div></div>"""
        html = (header + history_row() + history_row(
            time='01:02', result='10', winners='1,234', prizes='9,450,696'))
        rows = self.extract(html.replace('\n', ''))
        self.assertEqual(rows, [
            {'result': '19', 'timestamp': '2026-09-06 01:03:00',
             'winners_count': '467', 'prize_amount': '37006000'},
            {'result': '10', 'timestamp': '2026-09-06 01:02:00',
             'winners_count': '1234', 'prize_amount': '9450696'},
        ])

    def test_legacy_nested_result_and_decimal_prize(self):
        rows = self.extract(history_row(
            time='<span>21:37</span>', result='18 <div>(B/E)</div>',
            winners='371', prizes='1.25M'))
        self.assertEqual(rows[0]['result'], '18')
        self.assertEqual(rows[0]['prize_amount'], '1250000')
        self.assertEqual(rows[0]['timestamp'], '2026-09-06 21:37:00')

    def test_explicit_dates_and_undated_rows_across_midnight(self):
        rows = self.extract(''.join(history_row(time=time) for time in (
            '01:03', '00:00', '09.07 23:59', '09.07 00:00', '09.06 23:59')))
        self.assertEqual([row['timestamp'] for row in rows], [
            '2026-09-08 01:03:00', '2026-09-08 00:00:00',
            '2026-09-07 23:59:00', '2026-09-07 00:00:00',
            '2026-09-06 23:59:00',
        ])

    def test_undated_history_uses_configured_date_and_midnight_rollover(self):
        rows = self.extract(history_row(time='00:00') + history_row(time='23:59'))
        self.assertEqual([row['timestamp'] for row in rows], [
            '2026-09-06 00:00:00', '2026-09-05 23:59:00',
        ])

    def test_year_rollovers(self):
        for times, expected in (
            (('00:00', '12.31 23:59'),
             ['2027-01-01 00:00:00', '2026-12-31 23:59:00']),
            (('01.01 00:00', '12.31 23:59'),
             ['2026-01-01 00:00:00', '2025-12-31 23:59:00']),
        ):
            with self.subTest(times=times):
                rows = self.extract(''.join(history_row(time=time) for time in times))
                self.assertEqual([row['timestamp'] for row in rows], expected)

    def test_zero_values(self):
        rows = self.extract(history_row(result='0', winners='0', prizes='0'))
        self.assertEqual(rows[0]['result'], '0')
        self.assertEqual(rows[0]['winners_count'], '0')
        self.assertEqual(rows[0]['prize_amount'], '0')

    def test_invalid_input_preserves_existing_csv(self):
        for html in (
            '<div>No history</div>',
            history_row() + history_row(result=''),
            history_row() + history_row(winners='unknown'),
            history_row() + history_row(prizes='0.5'),
            history_row() + history_row(time='25:00'),
            history_row() + "<div class='van-cell-group'><div class='time'>01:00</div>",
        ):
            with self.subTest(html=html):
                self.output_file.write_text('existing export', encoding='utf-8')
                with self.assertRaises(ValueError):
                    self.extract(html)
                self.assertEqual(self.output_file.read_text(), 'existing export')


if __name__ == '__main__':
    unittest.main()
