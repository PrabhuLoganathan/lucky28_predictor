import fs from 'node:fs';
import path from 'node:path';

export const projectRoot = path.resolve(__dirname, '../..');

export function loadConfig(env = process.env) {
    const resolve = (value: string) => path.resolve(projectRoot, value);
    const tokenFile = resolve('.local/logger-token');
    const token = env.LUCKY28_LOGGER_TOKEN || (fs.existsSync(tokenFile) ? fs.readFileSync(tokenFile, 'utf8').trim() : '');
    if (!token) throw new Error('Logger token is missing. Run python3 run.py --setup from the project root.');
    const apiUrl = (env.LUCKY28_API_URL || `http://${env.LUCKY28_HOST || '127.0.0.1'}:${env.LUCKY28_PORT || '8000'}/api/logger`).replace(/\/$/, '');
    if (!['http:', 'https:'].includes(new URL(apiUrl).protocol)) throw new Error('LUCKY28_API_URL must use HTTP or HTTPS.');
    return {
        apiUrl, token,
        gameUrl: env.CHAMET_GAME_URL || 'https://webapp.chametw.com/partyList',
        profileDir: resolve(env.CHAMET_PROFILE_DIR || '.local/chamet-profile'),
        dataDir: resolve(env.CHAMET_DATA_DIR || '.local/chamet'),
        channel: env.CHAMET_BROWSER_CHANNEL || 'chrome',
        headless: env.CHAMET_HEADLESS === 'true',
        viewport: {
            width: Number(env.CHAMET_VIEWPORT_WIDTH || 375),
            height: Number(env.CHAMET_VIEWPORT_HEIGHT || 667),
        },
    };
}
