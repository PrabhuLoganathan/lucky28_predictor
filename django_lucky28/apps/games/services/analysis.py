import pandas as pd
import random
from typing import List, Dict, Tuple, Any

class AnalysisService:
    def __init__(self, df: pd.DataFrame = None):
        self.df = df

    @staticmethod
    def get_color(n: int) -> str:
        """Return color for number 0-27."""
        if n in [0, 1, 26, 27]: return "Red"
        if n in [2, 3, 24, 25]: return "Yellow"
        if n in [4, 5, 22, 23]: return "Pink"
        if n in [6, 7, 20, 21]: return "Blue"
        if n in [8, 9, 18, 19]: return "Cyan"
        if n in [10, 11, 16, 17]: return "Green"
        if n in [12, 13, 14, 15]: return "Grey"
        return "Unknown"

    @staticmethod
    def classify(n: int) -> Dict[str, Any]:
        """Classify a single number into its groups."""
        is_small = 0 <= n <= 13
        is_big = 14 <= n <= 27
        is_even = (n % 2 == 0)
        is_odd = not is_even
        
        combo = 'NA'
        if is_small and is_odd: combo = 'SO'
        elif is_small and is_even: combo = 'SE'
        elif is_big and is_odd: combo = 'BO'
        elif is_big and is_even: combo = 'BE'

        color = AnalysisService.get_color(n)

        return {
            'number': n,
            'is_small': is_small,
            'is_big': is_big,
            'is_even': is_even,
            'is_odd': is_odd,
            'combo': combo,
            'color': color,
            'size': 'Small' if is_small else 'Big',
            'parity': 'Even' if is_even else 'Odd'
        }

    @staticmethod
    def compute_stats(series: pd.Series) -> Tuple[Dict[str, Any], pd.Series, pd.DataFrame]:
        """Compute base statistics, frequency, and repetitions."""
        s = series.dropna().astype(int)
        total = len(s)
        base = {
            'small': 0, 'big': 0, 'odd': 0, 'even': 0,
            'SO': 0, 'SE': 0, 'BO': 0, 'BE': 0,
            'total': total
        }

        for n in s:
            c = AnalysisService.classify(n)
            if c['is_small']: base['small'] += 1
            if c['is_big']: base['big'] += 1
            if c['is_even']: base['even'] += 1
            if c['is_odd']: base['odd'] += 1
            if c['combo'] in base: base[c['combo']] += 1

        t = total or 1
        pct = {f'{k}_pct': (base[k] / t) * 100 for k in base if k != 'total'}
        freq = s.value_counts().sort_index()
        
        repeated = freq[freq > 1].reset_index()
        repeated.columns = ['number', 'count']
        
        return {**base, **pct}, freq, repeated

    @staticmethod
    def get_number_breakdown(freq: pd.Series) -> List[Dict[str, Any]]:
        """Detailed breakdown for each number 0-27."""
        idx = range(0, 28)
        freq = freq.reindex(idx, fill_value=0)
        total = freq.sum() or 1
        rows = []
        for n, c in freq.items():
            c_info = AnalysisService.classify(n)
            rows.append({
                'number': n,
                'count': int(c),
                'percent': round((c / total) * 100, 2),
                'size': c_info['size'],
                'parity': c_info['parity'],
                'combo': c_info['combo']
            })
        return rows

    @staticmethod
    def get_hot_cold(freq: pd.Series, top: int = 5) -> Tuple[List[Dict], List[Dict]]:
        """Get top N hot and cold numbers."""
        idx = range(0, 28)
        freq = freq.reindex(idx, fill_value=0)
        
        hot = freq.sort_values(ascending=False).head(top).reset_index()
        cold = freq.sort_values(ascending=True).head(top).reset_index()
        
        hot.columns = ['number', 'count']
        cold.columns = ['number', 'count']
        
        return hot.to_dict('records'), cold.to_dict('records')

    @staticmethod
    def get_streaks(series: pd.Series) -> Dict[str, Any]:
        """Calculate current and longest streaks."""
        s = series.dropna().astype(int)
        if s.empty: return {}

        def calc(labels):
            longest_label = None
            longest_len = 0
            prev = None
            length = 0
            
            # History Labels (Longest)
            for lab in labels:
                if lab == prev:
                    length += 1
                else:
                    if prev is not None and length > longest_len:
                        longest_len = length
                        longest_label = prev
                    prev = lab
                    length = 1
            if prev is not None and length > longest_len:
                longest_len = length
                longest_label = prev
            
            # Current Streak
            current_label = labels.iloc[-1]
            current_len = 0
            # iterate backwards
            for lab in labels.iloc[::-1]:
                if lab == current_label:
                    current_len += 1
                else:
                    break
            
            return {
                'longest_label': longest_label,
                'longest_len': int(longest_len),
                'current_label': current_label,
                'current_len': int(current_len)
            }

        size_labels = s.apply(lambda x: 'Small' if 0 <= x <= 13 else 'Big')
        parity_labels = s.apply(lambda x: 'Even' if x % 2 == 0 else 'Odd')
        
        return {
            'size': calc(size_labels),
            'parity': calc(parity_labels)
        }

    @staticmethod
    def get_empirical_probs(series: pd.Series, window: int) -> Dict[str, float]:
        """Calculate probabilities based on last N games."""
        s = series.dropna().astype(int).tail(window)
        if s.empty: return {}
        
        stats, _, _ = AnalysisService.compute_stats(s)
        t = stats['total'] or 1
        
        # Map to pure keys
        return {
            'small': stats['small'] / t,
            'big': stats['big'] / t,
            'odd': stats['odd'] / t,
            'even': stats['even'] / t,
            'SO': stats['SO'] / t,
            'SE': stats['SE'] / t,
            'BO': stats['BO'] / t,
            'BE': stats['BE'] / t
        }

    @staticmethod
    def simulate_streak(p_target: float, current_len: int, sims: int = 5000, max_extra: int = 20):
        """Monte Carlo simulation for streak continuation."""
        results = []
        for _ in range(sims):
            extra = 0
            while extra < max_extra:
                if random.random() < p_target:
                    extra += 1
                else:
                    break
            results.append(current_len + extra)
        
        s = pd.Series(results)
        dist = s.value_counts().sort_index().reset_index()
        dist.columns = ['length', 'count']
        dist['percent'] = (dist['count'] / sims) * 100
        return dist.to_dict('records')

    @staticmethod
    def analyze_window_repetition(series: pd.Series, window_size: int = 10):
        """Sliding window repetition analysis."""
        s = series.dropna().astype(int).reset_index(drop=True)
        n = len(s)
        if n < window_size: return []

        rows = []
        # We'll return the last 50 windows for display to avoid huge payloads
        start_idx = max(0, n - 200) 
        
        for i in range(start_idx + window_size - 1, n):
            window_slice = s.iloc[i - window_size + 1 : i + 1]
            freq = window_slice.value_counts()
            has_rep = (freq > 1).any()
            repeated = freq[freq > 1]
            
            rep_detail = ", ".join([f"{num}x{cnt}" for num, cnt in repeated.items()])
            
            rows.append({
                'window_index': i - window_size + 2, # 1-based, somewhat arbitrary
                'start_game_idx': i - window_size + 1,
                'end_game_idx': i,
                'has_repetition': has_rep,
                'unique_count': len(freq),
                'numbers': window_slice.tolist(),
                'repeated_detail': rep_detail
            })
        
        # Return reversed (newest first)
        return rows[::-1]

    @staticmethod
    def get_gap_analysis(series: pd.Series) -> Dict[str, Any]:
        """
        Calculate 'Gap' (Drought) - how many games since a number/category last appeared.
        """
        s = series.dropna().astype(int)
        if s.empty: return {}

        last_indices = {}
        total_len = len(s)
        
        # Iterate backwards to find latest index of each number
        for idx, val in enumerate(s):
            last_indices[val] = idx
            
        # Calculate gaps for Numbers 0-27
        number_gaps = {}
        for n in range(0, 28):
            if n in last_indices:
                # Gap = (Total - 1) - Last_Index
                # e.g. Total=10, Last Index=9 (latest) -> Gap 0
                number_gaps[n] = (total_len - 1) - last_indices[n]
            else:
                number_gaps[n] = total_len # Never seen in this series
                
        # Calculate Gaps for Categories (Big/Small, Odd/Even)
        # Efficient way: Scan backwards until we hit the condition
        reversed_s = s.tolist()[::-1]
        
        def find_gap(condition_fn):
            for i, val in enumerate(reversed_s):
                if condition_fn(val):
                    return i
            return total_len
            
        cat_gaps = {
            'small': find_gap(lambda x: 0 <= x <= 13),
            'big': find_gap(lambda x: 14 <= x <= 27),
            'odd': find_gap(lambda x: x % 2 != 0),
            'even': find_gap(lambda x: x % 2 == 0),
        }
        
        # Color Gaps
        # Map color -> numbers
        # Red: 0,1,26,27 | Yellow: 2,3,24,25 | Pink: 4,5,22,23 | Blue: 6,7,20,21 
        # Cyan: 8,9,18,19 | Green: 10,11,16,17 | Grey: 12,13,14,15
        color_map = {
            'Red': [0, 1, 26, 27],
            'Yellow': [2, 3, 24, 25],
            'Pink': [4, 5, 22, 23],
            'Blue': [6, 7, 20, 21],
            'Cyan': [8, 9, 18, 19],
            'Green': [10, 11, 16, 17],
            'Grey': [12, 13, 14, 15]
        }
        
        color_gaps = {}
        for c_name, nums in color_map.items():
            color_gaps[c_name] = find_gap(lambda x: x in nums)
        
        return {
            'numbers': number_gaps,
            'categories': cat_gaps,
            'colors': color_gaps
        }

    def get_repetition_analysis(self, window=10):
        """
        Sliding-window repetition analysis.
        Returns list of dicts for each window.
        """
        if self.df.empty or 'winning_number' not in self.df.columns:
            return []

        # Ensure sorted by ID/Time
        # Depending on how df was loaded. Usually it's filtered.
        # We assume self.df is the relevant dataset
        # We need to sort ASCENDING for the window slide to make sense naturally
        # But if self.df is DESC (Dashboard view), we should reverse it or handle indices properly.
        # Let's assume self.df is sorted DESC (Recent first).
        # So we reverse it to iterate chronologically? Or iterate backwards.
        
        # Taking a copy to be safe
        df = self.df.copy()
        
        # Sort ASC for sliding
        if 'id' in df.columns:
            df = df.sort_values('id', ascending=True)
        else:
            df = df.sort_index(ascending=True) # Assuming default index is roughly chronological/id-based
            
        df = df.dropna(subset=['winning_number'])
        df['winning_number'] = df['winning_number'].astype(int)
        
        n = len(df)
        if n < window:
            return []

        rows = []
        # Iterate windows
        # Window i ends at index i (inclusive), starts at i - window + 1
        for i in range(window - 1, n):
            window_slice = df.iloc[i - window + 1 : i + 1]
            nums = window_slice['winning_number']
            
            # Count freqs
            counts = nums.value_counts()
            repeated = counts[counts > 1]
            has_rep = not repeated.empty
            
            # Form details string
            rep_details = ", ".join([f"{num}x{cnt}" for num, cnt in repeated.items()])
            
            rows.append({
                'window_index': i - window + 2, # 1-based sequential index relative to filtered set
                'start_game': window_slice.get('game_no', pd.Series(['?']*len(window_slice))).iloc[0],
                'end_game': window_slice.get('game_no', pd.Series(['?']*len(window_slice))).iloc[-1],
                'numbers': nums.tolist(),
                'has_repetition': has_rep,
                'unique_count': len(counts),
                'repeated_details': rep_details
            })
            
        # Return sorted by most recent window (DESC)
        return rows[::-1]

    @staticmethod
    def get_predictions(gap_data: Dict[str, Any], probs: Dict[str, float]) -> List[str]:
        """
        Generate simple insights/"predictions" based on Gaps vs Probability.
        Logic: If Gap is significant/large, suggest it *might* be due.
        """
        insights = []
        
        if not gap_data or not probs:
            return []
            
        cats = gap_data.get('categories', {})
        
        # Simple threshold heuristic
        # If gap > 8 for Small/Big/Odd/Even, it's getting notable
        threshold = 6 
        
        for key in ['small', 'big', 'odd', 'even']:
            gap = cats.get(key, 0)
            if gap > threshold:
                prob_pct = probs.get(key, 0) * 100
                insights.append(f"**{key.title()}** is overdue (Gap: {gap}, Hist Prob: {prob_pct:.1f}%)")
                
        # Number insights - extreme outliers
        nums = gap_data.get('numbers', {})
        # Find max gap number
        sorted_gaps = sorted(nums.items(), key=lambda x: x[1], reverse=True)
        top_gap_num, top_gap_val = sorted_gaps[0]
        
        if top_gap_val > 50:
            insights.append(f"Number **{top_gap_num}** hasn't appeared in {top_gap_val} games (Cold).")
            
        return insights
