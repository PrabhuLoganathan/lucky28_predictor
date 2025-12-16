#!/usr/bin/env python
import os, sys
from pathlib import Path
from dotenv import load_dotenv

def main():
    # Load .env from project root (one level up from django_lucky28)
    env_path = Path(__file__).resolve().parent.parent / '.env'
    load_dotenv(dotenv_path=env_path)
    
    os.environ.setdefault('DJANGO_SETTINGS_MODULE','lucky28_backend.settings')
    from django.core.management import execute_from_command_line
    execute_from_command_line(sys.argv)
if __name__ == '__main__':
    main()
