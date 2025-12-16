#!/usr/bin/env python
import os, sys
from pathlib import Path
from dotenv import load_dotenv

def main():
    # Load .env from project root (one level up from django_lucky28)
    env_path = Path(__file__).resolve().parent.parent / '.env'
    load_dotenv(dotenv_path=env_path)
    
    # Add 'apps' folder to sys.path
    sys.path.append(str(Path(__file__).resolve().parent / 'apps'))

    os.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings')
    from django.core.management import execute_from_command_line
    execute_from_command_line(sys.argv)
if __name__ == '__main__':
    main()
