import re
import csv
import os
from datetime import datetime

# Input/Output paths
INPUT_FILE = '/Users/nilav/Documents/GitHub/lucky28_predictor/HistoryExtraction/14th.html'
OUTPUT_FILE = '/Users/nilav/Documents/GitHub/lucky28_predictor/HistoryExtraction/14th.csv'

# Date for timestamp (assuming 14th of current month/year 2025-12 based on file/context)
DATE_PREFIX = "2025-12-14"

def extract_data():
    try:
        with open(INPUT_FILE, 'r', encoding='utf-8') as f:
            content = f.read()

        # Regex patterns to find rows and data
        # Row start
        # We'll split by "van-cell-group" to get chunks, then parse each chunk
        results = []
        
        # Regex to find the blocks. 
        # Since the file is well formatted now, we can try robust regex or line-by-line.
        # Let's use a pattern that captures the content between van-cell-group divs
        
        # Simple approach: find all <div class="van-cell-group">...</div>
        # But regex dotall is greedy/non-greedy care needed.
        
        # specific patterns for fields
        # Time: <div class="time">21:37</div>
        # Result: <div class="result">\n\s*18
        # Winners: <div class="winners">\n\s*371
        # Prizes: <div class="prizes">... \n\s*22,551,671
        
        # Let's iterate over lines to be stateful, it's safer than complex regex on whole file
        
        current_row = {}
        rows = []
        
        lines = content.splitlines()
        in_row = False
        
        for i, line in enumerate(lines):
            line = line.strip()
            
            if 'class="van-cell-group"' in line:
                in_row = True
                current_row = {}
                continue
            
            if not in_row:
                continue
                
            # Parse Time
            if 'class="time"' in line:
                m = re.search(r'>(\d{2}:\d{2})<', line)
                if m:
                    current_row['time'] = m.group(1)
            
            # Parse Result (it might be on the same line or next)
            # <div class="result">
            #                18
            #                <div>(B/E)</div>
            if 'class="result"' in line:
                # Try to get number immediately if on same line
                # But in my formatting it was:
                # <div class="result">
                #   {{ item.result }}
                #   <div>...
                # Wait, I am parsing 14th.html which I saved.
                # Let's check the view_file I did earlier or the write I did.
                # My write was:
                # <div class="result">
                #    18 
                #    <div>(B/E)</div>
                # </div>
                # BUT, the original file had it like <div class="flex jc-c result">18 <div ...
                # My format script did:
                # .result { ... } 
                # It wrapped existing content. I did NOT change the inner HTML of the items much, just wrapped them?
                # Actually, I used `existing_content` variable in the python script.
                # So the inner HTML structure is preserved from the original file I read.
                pass

        # Use robust regex on the whole content as the structure is repetitive
        
        # Find all row blocks
        row_pattern = r'<div[^>]*class="[^"]*van-cell-group[^"]*"[^>]*>(.*?)</div>\s*(?=<div|</body>)'
        # Note: the div might not close immediately if nested, but van-cell-group seems to be a container.
        # Actually, `14th.html` was a list of siblings. 
        
        # Alternative: The file format I saved uses indentation.
        # Let's try matching specific unique signatures in order.
        
        # Pattern for Time
        times = re.findall(r'<div[^>]*class="time"[^>]*>\s*(\d{2}:\d{2})\s*</div>', content)
        
        # Pattern for Result
        # Original: <div data-v-10f9d334="" class="flex jc-c result">18 <div data-v-10f9d334="">(B/E)</div></div>
        # My Formatted: <div class="result">... 
        # Wait, my wrapper script ADDED classes or just styles?
        # My script: 
        # html_template_start + existing_content + html_template_end
        # The existing content had: <div data-v-10f9d334="" class="van-cell-group ..."> ... </div>
        # So I did NOT change the inner classes like "flex jc-c result".
        # I just added CSS for `.result`.
        
        results_vals = re.findall(r'class="[^"]*result[^"]*">\s*(\d+)\s*<div', content)
        
        # Pattern for Winners
        # <div class="winners table_num"><img ...> 371</div>
        # OR without img if display none: <div ...> 371</div>
        # Regex to capture text after > and before <, ignoring img tag if present
        # winners_vals = re.findall(r'class="[^"]*winners[^"]*">.*?(\d+)\s*</div>', content, re.DOTALL)
        # This is tricky with optional img.
        # Let's match the number specifically inside the winners div.
        winners_vals = []
        # Find all winners divs
        winner_divs = re.findall(r'class="[^"]*winners[^"]*">(.*?)</div>', content, re.DOTALL)
        for w in winner_divs:
            # Remove html tags first to avoid matching numbers in attributes (e.g. data-v-10...)
            text = re.sub(r'<[^>]+>', '', w).strip()
            # Extract number
            num = re.search(r'(\d+)', text)
            if num:
                winners_vals.append(num.group(1))
            else:
                winners_vals.append('0')

        # Pattern for Prizes
        # <div class="prizes table_num"><img ...> 22,551,671 <i ...></i></div>
        prize_divs = re.findall(r'class="[^"]*prizes[^"]*">(.*?)</div>', content, re.DOTALL)
        prizes_vals = []
        for p in prize_divs:
            # Remove img tag, i tag, commas
            text = re.sub(r'<[^>]+>', '', p) # remove html tags
            text = text.replace(',', '').strip()
            # Extract number
            num = re.search(r'(\d+)', text)
            if num:
                prizes_vals.append(num.group(1))
            else:
                prizes_vals.append('0')

        # Combine
        data = []
        length = min(len(times), len(results_vals), len(winners_vals), len(prizes_vals))
        
        print(f"Found {len(times)} times, {len(results_vals)} results, {len(winners_vals)} winners, {len(prizes_vals)} prizes")
        
        for i in range(length):
            timestamp = f"{DATE_PREFIX} {times[i]}:00"
            data.append({
                'result': results_vals[i],
                'timestamp': timestamp,
                'winners_count': winners_vals[i],
                'prize_amount': prizes_vals[i]
            })

        # Write CSV
        with open(OUTPUT_FILE, 'w', newline='', encoding='utf-8') as csvfile:
            fieldnames = ['result', 'timestamp', 'winners_count', 'prize_amount']
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)

            writer.writeheader()
            for row in data:
                writer.writerow(row)
                
        print(f"Successfully wrote {length} rows to {OUTPUT_FILE}")

    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    extract_data()
