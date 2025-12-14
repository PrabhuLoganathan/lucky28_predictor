import streamlit as st
import pandas as pd
import random
from db import get_conn, db_exists


TABLE = 'gameapp_gameresult'


def classify(n: int):
    is_small = 0 <= n <= 13
    is_big = 14 <= n <= 27
    is_even = (n % 2 == 0)
    is_odd = not is_even
    if is_small and is_odd:
        combo = 'SO'
    elif is_small and is_even:
        combo = 'SE'
    elif is_big and is_odd:
        combo = 'BO'
    elif is_big and is_even:
        combo = 'BE'
    else:
        combo = 'NA'
    return is_small, is_big, is_even, is_odd, combo


def load_data():
    if not db_exists():
        return pd.DataFrame(columns=['id', 'result', 'timestamp', 'source_file', 'created_at'])
    with get_conn() as conn:
        try:
            df = pd.read_sql_query(
                f'SELECT id, result, timestamp, source_file, created_at FROM {TABLE} ORDER BY id ASC',
                conn,
                parse_dates=['timestamp', 'created_at'],
            )
        except Exception:
            df = pd.DataFrame(columns=['id', 'result', 'timestamp', 'source_file', 'created_at'])
    return df


def compute_stats(series: pd.Series):
    s = series.dropna().astype(int)
    total = len(s)
    base = {
        'small': 0,
        'big': 0,
        'odd': 0,
        'even': 0,
        'SO': 0,
        'SE': 0,
        'BO': 0,
        'BE': 0,
    }
    for n in s:
        is_small, is_big, is_even, is_odd, combo = classify(n)
        if is_small:
            base['small'] += 1
        if is_big:
            base['big'] += 1
        if is_even:
            base['even'] += 1
        if is_odd:
            base['odd'] += 1
        base[combo] += 1
    base['total'] = total
    t = total or 1
    pct = {f'{k}_pct': (base[k] / t) * 100 for k in base if k != 'total'}
    freq = s.value_counts().sort_index()
    repeated = freq[freq > 1].reset_index()
    repeated.columns = ['number', 'count']
    return {**base, **pct}, freq, repeated


def number_breakdown(freq: pd.Series):
    idx = range(0, 28)
    freq = freq.reindex(idx, fill_value=0)
    total = freq.sum() or 1
    rows = []
    for n, c in freq.items():
        is_small, is_big, is_even, is_odd, combo = classify(n)
        rows.append(
            {
                'number': n,
                'count': int(c),
                'percent': round((c / total) * 100, 2),
                'size': 'Small' if is_small else 'Big',
                'parity': 'Even' if is_even else 'Odd',
                'combo': combo,
            }
        )
    return pd.DataFrame(rows)


def hot_cold(freq: pd.Series, top=5):
    idx = range(0, 28)
    freq = freq.reindex(idx, fill_value=0)
    hot = freq.sort_values(ascending=False).head(top).reset_index()
    cold = freq.sort_values(ascending=True).head(top).reset_index()
    hot.columns = ['number', 'count']
    cold.columns = ['number', 'count']
    return hot, cold


def streaks(series: pd.Series):
    s = series.dropna().astype(int)
    if s.empty:
        return {}

    def calc(labels):
        longest_label = None
        longest_len = 0
        prev = None
        length = 0
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
        current_label = labels.iloc[-1]
        current_len = 1
        for lab in labels.iloc[:-1].iloc[::-1]:
            if lab == current_label:
                current_len += 1
            else:
                break
        return {
            'longest_label': longest_label,
            'longest_len': int(longest_len),
            'current_label': current_label,
            'current_len': int(current_len),
        }

    size_labels = s.apply(lambda x: 'Small' if 0 <= x <= 13 else 'Big')
    parity_labels = s.apply(lambda x: 'Even' if x % 2 == 0 else 'Odd')
    return {'size': calc(size_labels), 'parity': calc(parity_labels)}


def empirical(series: pd.Series, window: int):
    s = series.dropna().astype(int).tail(window)
    if s.empty:
        return {}
    stats, _, _ = compute_stats(s)
    t = stats['total'] or 1
    return {k: stats[k] / t for k in ['small', 'big', 'odd', 'even', 'SO', 'SE', 'BO', 'BE']}


def simulate_streak_continuation(p_target: float, current_len: int, sims: int = 5000, max_extra: int = 20):
    """Simulate how long a current streak might continue."""
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
    return s.value_counts().sort_index()


def window_repetition_analysis(df: pd.DataFrame, window: int = 10) -> pd.DataFrame:
    """
    Sliding-window repetition analysis over the filtered data.
    Each row = one window of `window` consecutive games.
    """
    if 'result' not in df.columns:
        return pd.DataFrame()

    # Prepare sequence sorted by id if available
    if 'id' in df.columns:
        seq_df = df[['id', 'result', 'timestamp']].dropna(subset=['result']).copy()
        seq_df = seq_df.sort_values('id')
    else:
        seq_df = df[['result', 'timestamp']].dropna(subset=['result']).copy()
        seq_df = seq_df.reset_index(drop=True)

    seq_df = seq_df.reset_index(drop=True)
    seq_df['game_index'] = seq_df.index + 1
    n = len(seq_df)
    if n < window:
        return pd.DataFrame()

    rows = []
    for i in range(window - 1, n):
        window_df = seq_df.iloc[i - window + 1 : i + 1]
        nums = window_df['result'].astype(int)
        freq = nums.value_counts().sort_index()
        repeated = freq[freq > 1]
        has_rep = not repeated.empty
        repeated_str = ', '.join(f'{num}×{cnt}' for num, cnt in repeated.items())

        rows.append(
            {
                'Window #': i - window + 2,  # 1-based
                'Start game #': int(window_df['game_index'].iloc[0]),
                'End game #': int(window_df['game_index'].iloc[-1]),
                'Has repetition': 'YES' if has_rep else 'NO',
                'Unique count': int(freq.size),
                'Numbers (old→new)': ', '.join(str(x) for x in nums.tolist()),
                'Repeated detail': repeated_str,
            }
        )

    return pd.DataFrame(rows)


def style_status_chip(row):
    """
    Style the 'Status' column as a color chip based on repetition.
    """
    styles = [''] * len(row)
    cols = list(row.index)

    if 'Status' in cols and 'Has repetition' in cols:
        idx = cols.index('Status')
        if row['Has repetition'] == 'YES':
            # Red chip for repetition
            styles[idx] = (
                'background-color: #fee2e2; '
                'color: #991b1b; '
                'font-weight: bold; '
                'text-align: center; '
                'border-radius: 999px; '
                'padding: 4px 8px; '
                'border: 1px solid #fecaca;'
            )
        else:
            # Green chip for all-unique
            styles[idx] = (
                'background-color: #dcfce7; '
                'color: #166534; '
                'font-weight: bold; '
                'text-align: center; '
                'border-radius: 999px; '
                'padding: 4px 8px; '
                'border: 1px solid #bbf7d0;'
            )
    return styles


# ---------------- UI -----------------
st.set_page_config(page_title='Lucky 28 Pro Dashboard', layout='wide')
st.title('🎰 Lucky 28 – Pro History Dashboard')

if not db_exists():
    st.error('Database lucky28.db not found. Run Django migrations and import CSV via admin first.')
    st.stop()

df_all = load_data()
if df_all.empty:
    st.warning('No data yet. Import CSV via Django Admin → Game Results → Import CSV.')
    st.stop()

st.sidebar.header('📂 Data Filters')
min_ts = df_all['timestamp'].min()
max_ts = df_all['timestamp'].max()

if pd.isna(min_ts) or pd.isna(max_ts):
    st.sidebar.info('Timestamps missing for some/all rows; date filter disabled.')
    df = df_all.copy()
else:
    start_date = st.sidebar.date_input('Start date', min_ts.date())
    end_date = st.sidebar.date_input('End date', max_ts.date())
    mask = (df_all['timestamp'].dt.date >= start_date) & (df_all['timestamp'].dt.date <= end_date)
    df = df_all[mask].copy()
    st.caption(f'Filtered to **{len(df)}** rows between {start_date} and {end_date}.')

if df.empty:
    st.warning('No rows after applying date filter. Adjust the filter.')
    st.stop()

total_len = len(df)
last_n = st.sidebar.slider('Recent window (N games)', 10, min(2000, total_len), min(100, total_len), step=10)
hotcold_window = st.sidebar.slider('Hot/Cold window', 50, min(5000, total_len), min(200, total_len), step=50)
prob_window = st.sidebar.slider('Probability window', 50, min(5000, total_len), min(200, total_len), step=50)
top_n = st.sidebar.slider('Top N hot/cold numbers', 3, 10, 5)

page = st.sidebar.radio(
    'Page',
    [
        'Dashboard',
        'Number Breakdown',
        'Streaks & Probabilities',
        'Combo Sequences',
        '10-Game Repetition',
        'Streak Simulator',
        'Raw Data',
    ],
)

recent_series = df['result'].tail(last_n)
overall_stats, overall_freq, _ = compute_stats(df['result'])
recent_stats, recent_freq, recent_repeated = compute_stats(recent_series)


def stats_block(stats, title):
    st.subheader(title)
    st.write(f"Total games: **{stats['total']}**")
    c1, c2, c3 = st.columns(3)
    with c1:
        st.metric('Small (0–13)', f"{stats['small']} ({stats['small_pct']:.1f}%)")
        st.metric('Big (14–27)', f"{stats['big']} ({stats['big_pct']:.1f}%)")
    with c2:
        st.metric('Odd', f"{stats['odd']} ({stats['odd_pct']:.1f}%)")
        st.metric('Even', f"{stats['even']} ({stats['even_pct']:.1f}%)")
    with c3:
        st.write('SO / SE / BO / BE')
        st.write(
            f"SO: {stats['SO']} ({stats['SO_pct']:.1f}%)  |  "
            f"SE: {stats['SE']} ({stats['SE_pct']:.1f}%)  \n"
            f"BO: {stats['BO']} ({stats['BO_pct']:.1f}%)  |  "
            f"BE: {stats['BE']} ({stats['BE_pct']:.1f}%)"
        )


if page == 'Dashboard':
    st.header('📊 Overview')
    col1, col2 = st.columns(2)
    with col1:
        stats_block(overall_stats, 'Overall (filtered)')
    with col2:
        stats_block(recent_stats, f'Recent (last {last_n} games)')

    st.markdown('---')
    st.subheader('📈 Trend of Results (by timestamp)')
    if 'timestamp' in df.columns and df['timestamp'].notna().any():
        trend_df = df[['timestamp', 'result']].dropna().set_index('timestamp')
        st.line_chart(trend_df)
    else:
        st.info('No timestamps available for trend line.')

    st.markdown('---')
    st.subheader('🔥 Hot & ❄️ Cold Numbers')
    _, window_freq, _ = compute_stats(df['result'].tail(hotcold_window))
    hot_df, cold_df = hot_cold(window_freq, top=top_n)
    c1, c2 = st.columns(2)
    with c1:
        st.write(f'🔥 Hot (last {hotcold_window})')
        st.dataframe(hot_df, use_container_width=True)
    with c2:
        st.write(f'❄️ Cold (last {hotcold_window})')
        st.dataframe(cold_df, use_container_width=True)

elif page == 'Number Breakdown':
    st.header('🔢 Number Breakdown (0–27)')
    breakdown = number_breakdown(overall_freq)
    st.dataframe(breakdown, use_container_width=True, height=500)
    st.subheader('Bar Chart – Frequency of Each Number')
    st.bar_chart(breakdown.set_index('number')['count'])

    st.subheader('Download CSV')
    st.download_button(
        'Download breakdown.csv',
        breakdown.to_csv(index=False).encode('utf-8'),
        file_name='number_breakdown.csv',
        mime='text/csv',
    )

elif page == 'Streaks & Probabilities':
    st.header('📈 Streaks')
    streak_info = streaks(df['result'])
    if streak_info:
        cs, cp = st.columns(2)
        with cs:
            st.subheader('Size (Small / Big)')
            st.write(
                f"Longest: **{streak_info['size']['longest_label']}** "
                f"for **{streak_info['size']['longest_len']}** games"
            )
            st.write(
                f"Current: **{streak_info['size']['current_label']}** "
                f"for **{streak_info['size']['current_len']}** games"
            )
        with cp:
            st.subheader('Parity (Odd / Even)')
            st.write(
                f"Longest: **{streak_info['parity']['longest_label']}** "
                f"for **{streak_info['parity']['longest_len']}** games"
            )
            st.write(
                f"Current: **{streak_info['parity']['current_label']}** "
                f"for **{streak_info['parity']['current_len']}** games"
            )
    else:
        st.info('Not enough data for streaks.')

    st.markdown('---')
    st.header(f'🎯 Empirical Probabilities (last {prob_window} games)')
    probs = empirical(df['result'], prob_window)
    if probs:
        prob_df = pd.DataFrame(
            [{'Group': k, 'Probability (%)': round(v * 100, 2)} for k, v in probs.items()]
        )
        st.dataframe(prob_df, use_container_width=True)
        st.caption('These are historical frequencies, not guaranteed future outcomes.')
    else:
        st.info('Not enough data in selected window.')

    st.markdown('---')
    st.header(f'🔁 Repetition in Last {last_n} Games')
    st.write(list(recent_series.values))
    st.subheader('Numbers repeated at least twice')
    if recent_repeated.empty:
        st.write('No repetitions.')
    else:
        st.dataframe(recent_repeated, use_container_width=False)

elif page == 'Combo Sequences':
    st.header('🔗 Combo Sequences (SO / SE / BO / BE)')

    seq_df = df[['id', 'result']].dropna().copy() if 'id' in df.columns else df[['result']].dropna().copy()
    if 'id' in seq_df.columns:
        seq_df = seq_df.sort_values('id')
    else:
        seq_df = seq_df.reset_index(drop=True)

    # Map each result to its combo group
    seq_df['result'] = seq_df['result'].astype(int)
    seq_df['combo'] = seq_df['result'].apply(lambda n: classify(n)[4])

    # Add a simple running index so it's easy to talk about "Game 1, Game 2, ..."
    seq_df = seq_df.reset_index(drop=True)
    seq_df['game_index'] = seq_df.index + 1

    st.caption('Using filtered data and current date window from the sidebar.')

    # Grouped rows preview (recent at top)
    st.subheader('Compact combo sequence preview (Recent at Top)')
    
    # Get all combos, recent first
    all_combos = seq_df['combo'].tolist()[::-1]
    
    if all_combos:
        grouped_rows = []
        if all_combos:
            current_group = [all_combos[0]]
            for c in all_combos[1:]:
                if c == current_group[-1]:
                    current_group.append(c)
                else:
                    grouped_rows.append(current_group)
                    current_group = [c]
            grouped_rows.append(current_group)
        
        # Display top N groups
        max_groups = 50
        for group in grouped_rows[:max_groups]:
            # Join with comma
            row_str = ', '.join(group)
            st.text(row_str)
            
        if len(grouped_rows) > max_groups:
            st.caption('...')
    else:
        st.info('No combo data available in current filter.')

    st.markdown('---')
    st.subheader('Full sequence table')

    display_cols = ['game_index', 'id', 'result', 'combo'] if 'id' in seq_df.columns else ['game_index', 'result', 'combo']
    renamed = {
        'game_index': 'Game #',
        'result': 'Number',
        'combo': 'Combo',
    }
    if 'id' in seq_df.columns:
        renamed['id'] = 'Row ID'

    st.dataframe(
        seq_df[display_cols].rename(columns=renamed),
        use_container_width=True,
        height=400,
    )

    # Find the longest run where the same combo repeats without breaking (overall best streak)
    combos = seq_df['combo'].tolist()
    if combos:
        best_label = None
        best_len = 0
        best_start = 0

        current_label = None
        current_len = 0
        current_start = 0

        for i, lab in enumerate(combos):
            if lab == current_label:
                current_len += 1
            else:
                current_label = lab
                current_len = 1
                current_start = i

            if current_len > best_len:
                best_len = current_len
                best_label = current_label
                best_start = current_start

        best_end = best_start + best_len - 1
        start_game = best_start + 1
        end_game = best_end + 1

        st.markdown('---')
        st.subheader('🔥 Maximum repeated combo sequence (overall, filtered data)')
        c1, c2, c3 = st.columns(3)
        with c1:
            st.metric('Combo', best_label)
        with c2:
            st.metric('Length (games in a row)', best_len)
        with c3:
            st.metric('From game → to game', f'{start_game} → {end_game}')

        # Also compute per-combo max streaks
        st.markdown('---')
        st.subheader('📊 Per-combo maximum streaks')
        per_combo_rows = []
        for target in ['SO', 'SE', 'BO', 'BE']:
            max_len = 0
            max_start = None

            cur_len = 0
            cur_start = None

            for i, lab in enumerate(combos):
                if lab == target:
                    if cur_len == 0:
                        cur_start = i
                    cur_len += 1
                else:
                    if cur_len > 0 and cur_len > max_len:
                        max_len = cur_len
                        max_start = cur_start
                    cur_len = 0
                    cur_start = None

            # final flush
            if cur_len > 0 and cur_len > max_len:
                max_len = cur_len
                max_start = cur_start

            if max_len > 0:
                s_game = max_start + 1
                e_game = max_start + max_len
            else:
                s_game = None
                e_game = None

            per_combo_rows.append(
                {
                    'Combo': target,
                    'Max streak length': max_len,
                    'Start game #': s_game,
                    'End game #': e_game,
                }
            )

        st.dataframe(
            pd.DataFrame(per_combo_rows),
            use_container_width=True,
        )

        st.caption(
            'The first card shows the absolute longest combo streak. The table above breaks it down '
            'for each combo (SO / SE / BO / BE) separately, using only the filtered data range.'
        )
    else:
        st.info('No combo data available in current filter.')

elif page == '10-Game Repetition':
    st.header('🔁 10-Game Window Repetition Analysis')

    WINDOW_SIZE = 10
    rep_df = window_repetition_analysis(df, window=WINDOW_SIZE)

    if rep_df.empty:
        st.info(f'Not enough data (need at least {WINDOW_SIZE} games after filters).')
    else:
        # Add a status label for chips
        rep_df['Status'] = rep_df['Has repetition'].map(
            lambda v: '🔴 Repeat' if v == 'YES' else '🟢 All Unique'
        )

        total_windows = len(rep_df)
        with_rep = (rep_df['Has repetition'] == 'YES').sum()
        no_rep = total_windows - with_rep

        c1, c2, c3 = st.columns(3)
        with c1:
            st.metric('Total windows', total_windows)
        with c2:
            st.metric('With repetition', with_rep)
        with c3:
            st.metric('All-unique windows', no_rep)

        st.markdown('---')
        st.subheader(f'Latest window (last {WINDOW_SIZE} games)')

        latest = rep_df.iloc[-1]
        st.write(f"Window #: **{latest['Window #']}**")
        st.write(f"Games: **{latest['Start game #']} → {latest['End game #']}**")
        st.write(f"Status: {latest['Status']}")
        st.write(f"Numbers (old→new): `{latest['Numbers (old→new)']}`")
        st.write(f"Has repetition: **{latest['Has repetition']}**")
        if latest['Has repetition'] == 'YES' and latest['Repeated detail']:
            st.write(f"Repeated numbers: **{latest['Repeated detail']}**")
        else:
            st.write('No repeated numbers in this 10-game window.')

        st.markdown('---')
        st.subheader('Recent windows overview')

        # Show most recent windows at top
        show_n = st.slider('Show last N windows', 10, min(200, total_windows), 50, step=10)

        display_cols = [
            'Window #',
            'Status',
            'Start game #',
            'End game #',
            'Has repetition',
            'Unique count',
            'Numbers (old→new)',
            'Repeated detail',
        ]

        recent_df = rep_df[display_cols].tail(show_n).sort_values('Window #', ascending=False)
        styled_recent = recent_df.style.apply(style_status_chip, axis=1)
        st.dataframe(styled_recent, use_container_width=True, height=400)

        st.markdown('---')
        st.subheader('Only all-unique windows (optional)')
        unique_only = rep_df[rep_df['Has repetition'] == 'NO']
        if unique_only.empty:
            st.write('No all-unique 10-game windows found in current filter.')
        else:
            unique_df = unique_only[display_cols].tail(show_n).sort_values('Window #', ascending=False)
            styled_unique = unique_df.style.apply(style_status_chip, axis=1)
            st.dataframe(styled_unique, use_container_width=True, height=300)

elif page == 'Streak Simulator':
    st.header('🧪 Streak Continuation Simulator')

    probs = empirical(df['result'], prob_window)
    if not probs:
        st.info('Not enough data to build probabilities. Try increasing the window or importing more games.')
    else:
        streak_type = st.radio(
            'Streak type',
            ['Size (Small/Big)', 'Parity (Odd/Even)', 'Combo (SO/SE/BO/BE)'],
            horizontal=True,
        )

        target_label = None
        key_for_prob = None

        if streak_type == 'Size (Small/Big)':
            target_label = st.selectbox('Target', ['Small', 'Big'])
            key_for_prob = 'small' if target_label == 'Small' else 'big'
        elif streak_type == 'Parity (Odd/Even)':
            target_label = st.selectbox('Target', ['Odd', 'Even'])
            key_for_prob = 'odd' if target_label == 'Odd' else 'even'
        else:
            target_label = st.selectbox('Target', ['SO', 'SE', 'BO', 'BE'])
            key_for_prob = target_label

        p_target = probs.get(key_for_prob, 0.0)
        st.write(
            f'Empirical probability for **{target_label}** (last {prob_window} games): '
            f'**{p_target * 100:.2f}%**'
        )

        if p_target <= 0:
            st.warning('This group did not occur in the selected window. Simulation not meaningful.')
        elif p_target >= 1:
            st.warning('This group occurred 100% of the time in the window. Simulation would never break.')
        else:
            streak_info = streaks(df['result'])
            default_len = 1
            if streak_type == 'Size (Small/Big)' and streak_info:
                default_len = streak_info['size']['current_len']
            elif streak_type == 'Parity (Odd/Even)' and streak_info:
                default_len = streak_info['parity']['current_len']

            current_len = st.number_input(
                'Current streak length (how many times in a row already?)',
                min_value=1,
                max_value=100,
                value=int(default_len),
            )
            sims = st.slider('Number of simulations', 1000, 20000, 5000, step=1000)
            max_extra = st.slider(
                'Maximum extra games to simulate on top of current streak',
                5,
                50,
                20,
                step=1,
            )

            if st.button('Run simulation'):
                freq_series = simulate_streak_continuation(
                    p_target=p_target,
                    current_len=current_len,
                    sims=sims,
                    max_extra=max_extra,
                )
                sim_df = freq_series.reset_index()
                sim_df.columns = ['final_streak_length', 'count']
                sim_df['percentage'] = sim_df['count'] / sims * 100

                st.subheader('Distribution of possible final streak lengths')
                st.dataframe(sim_df, use_container_width=True)

                st.subheader('Streak length probability chart')
                st.bar_chart(sim_df.set_index('final_streak_length')['percentage'])

                st.caption(
                    'This is a Monte-Carlo simulation using historical frequencies as probabilities. '
                    'It does not predict or guarantee future outcomes; it only shows how streaks '
                    'typically behave under those assumptions.'
                )

else:  # Raw Data
    st.header('📄 Raw Data')
    st.dataframe(df.sort_values('id', ascending=False), use_container_width=True, height=600)
    st.caption('Showing filtered rows. Use sidebar to adjust date range and windows.')
