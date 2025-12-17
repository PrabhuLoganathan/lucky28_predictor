import pandas as pd
import random
from typing import List, Dict, Tuple, Any

class AnalysisService:
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

        return {
            'number': n,
            'is_small': is_small,
            'is_big': is_big,
            'is_even': is_even,
            'is_odd': is_odd,
            'combo': combo,
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
        
        return {
            'numbers': number_gaps,
            'categories': cat_gaps
        }

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
