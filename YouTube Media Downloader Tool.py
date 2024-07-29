import os
import configparser
import subprocess
from urllib.parse import urlparse, parse_qs
import readchar
import pyperclip
from colorama import init, Fore
import tkinter as tk
from tkinter import filedialog

config = configparser.ConfigParser()
init(autoreset=True)
root = tk.Tk()
root.withdraw()  # Hide the main window 

def select_directory():
    root = tk.Tk()
    root.withdraw()  # Hide the main window
    folder_selected = filedialog.askdirectory()  # Open the file dialog
    return folder_selected

def read_config():
    config.read('config.ini')
    return config.get('DEFAULT', 'output_dir', fallback=os.path.join(os.path.expanduser("~"), "Videos", "YouTube"))

def write_config(output_dir):
    config = configparser.ConfigParser()
    config['DEFAULT'] = {'output_dir': output_dir}
    with open('config.ini', 'w') as configfile:
        config.write(configfile)

def is_valid_youtube_url(url):
    parsed_url = urlparse(url)
    if parsed_url.netloc not in ['www.youtube.com', 'youtube.com', 'youtu.be']:
        return False, False

    qs = parse_qs(parsed_url.query)
    if parsed_url.path == '/watch':
        return 'v' in qs, False
    elif parsed_url.path == '/playlist':
        return 'list' in qs, True
    else:
        return False, False

def clear_screen():
    os.system('cls' if os.name == 'nt' else 'clear')

def get_user_input(output_dir):
    while True:
        print(Fore.RESET + 'Press "SPACE" to paste your copied YouTube URL from your clipboard (Video or Playlist).\n'
              f'Your downloads will be stored at: "{read_config()}"'
              '\n\nOR\n\n'
              'Press "CTRL + O" to change output directory.\n'
              'Press "CTRL + D" to open the current directory.\n'
              'Press "ENTER" to quit.\n')

        user_input = readchar.readkey()

        if user_input == readchar.key.ENTER:
            clear_screen()
            break
        elif user_input.lower() == readchar.key.CTRL_D:
            os.makedirs(read_config(), exist_ok=True)
            open_directory(read_config())
            clear_screen()
            print(Fore.GREEN + f'\n----- Opening Directory: {read_config()} -----\n\n')
            continue
        elif user_input.lower() == readchar.key.CTRL_O:
            clear_screen()
            if change_output_directory():
                continue
            else:
                clear_screen()
                break
        elif user_input.lower() == readchar.key.SPACE:
            url = pyperclip.paste().strip()
            clear_screen()
            print(Fore.YELLOW + f'\nPasted URL from clipboard: {url}\n')
        else:
            clear_screen()
            continue

        is_valid, is_playlist = is_valid_youtube_url(url)
        if not is_valid:
            clear_screen()
            print(Fore.RED + '\n----- Invalid YouTube URL. Please try again. -----\n\n')
            continue

        clear_screen()
        print('Press BACKSPACE to go back.\n\nChoose your format.\n\n1 = MP4 (Video Format)\n2 = MP3 (Audio Format)\n')
        fmt_choice = readchar.readkey()
        if fmt_choice == readchar.key.BACKSPACE:
            clear_screen()
            continue
        elif fmt_choice == '1' or fmt_choice == '\n':
            fmt = 'mp4'
        elif fmt_choice == '2':
            fmt = 'mp3'
        else:
            clear_screen()
            print(Fore.RED + '\n----- Invalid format. Please try again. -----\n\n')
            continue

        quality_option = None
        if fmt == 'mp4':
            clear_screen()
            print('Press BACKSPACE to go back.\n\nChoose Quality:\n1 = Best quality, suitable for watching (VP9 Compression).\n'
                  '2 = Lower quality, suitable for video editing (AVC1 Compression).\n\nPress 1 or 2:\n')
            quality_option = readchar.readkey()
            if quality_option == readchar.key.BACKSPACE:
                clear_screen()
                continue
            if quality_option not in ['1', '2']:
                clear_screen()
                print(Fore.RED + '\n----- Invalid choice. Please try again. -----\n\n')
                continue

        return url, fmt, output_dir, is_playlist, quality_option


def change_output_directory():
    while True:
        print(Fore.RESET + 'Select the new output directory for downloads.\n'
              f"Press Cancel to store downloads in the default directory ({os.path.join(os.path.expanduser('~'), 'Videos', 'YouTube')})."
              '\n\nDirectory:\n')
        folder_selected = filedialog.askdirectory()  # Open the file dialog
        new_output_dir = folder_selected
        if new_output_dir.lower() == 'back':
            clear_screen()
            return True
        if not new_output_dir:
            new_output_dir = os.path.join(os.path.expanduser("~"), "Videos", "YouTube")
        write_config(new_output_dir)
        clear_screen()
        print(Fore.GREEN + f'\n----- Output directory changed to: {new_output_dir} -----\n\n')
        return True


def open_directory(directory):
    if os.name == 'nt':
        os.startfile(directory)
    elif os.name == 'posix':
        subprocess.run(['open', directory])

def download_video(url, fmt, output_dir, is_playlist, quality_option):
    clear_screen()
    print(Fore.YELLOW + f'\n----- Downloading in {fmt.upper()} format... -----\n')
    output_template = f"{output_dir}/%(playlist)s/%(title)s.%(ext)s" if is_playlist else f"{output_dir}/%(title)s.%(ext)s"

    # Get the paths for yt-dlp and ffmpeg
    yt_dlp_path = os.path.join('dependencies', 'yt-dlp.exe')
    ffmpeg_path = os.path.join('dependencies', 'ffmpeg.exe')
    
    try:
        if fmt in ['mp3', 'wav']:
            subprocess.run([yt_dlp_path, '-f', 'bestaudio/best', '--extract-audio', '--audio-format', fmt, '--ffmpeg-location', ffmpeg_path, '-o', output_template, url], check=True)
        else:
            quality_format = 'bestvideo[vcodec^=avc1][height<=1080]+bestaudio[acodec^=mp4a]/best[vcodec^=avc1][height<=1080]' if quality_option == '2' else 'bestvideo+bestaudio'
            subprocess.run([yt_dlp_path, '-f', quality_format, '--merge-output-format', 'mp4', '--postprocessor-args', f'-c:a aac', '--ffmpeg-location', ffmpeg_path, '-o', output_template, url], check=True)
        print(Fore.GREEN + "\n----------- Download Complete -----------\n")
    except subprocess.CalledProcessError as e:
        print(Fore.RED + f"An error occurred: {e}")
        return
    except Exception as e:
        print(Fore.RED + f"Unexpected error: {e}")
        return

    print(Fore.RESET + "Would you like to open the folder where the downloaded file is stored? (Y/N)\n")
    open_dir_prompt = readchar.readkey().lower()
    if open_dir_prompt == 'y':
        open_directory(output_dir)
    clear_screen()


def main():
    
    if not os.path.exists('config.ini'):
        initial_output_dir = os.path.join(os.path.expanduser("~"), "Videos", "YouTube")
        write_config(initial_output_dir)
        clear_screen()

    output_dir = read_config()
    while True:
        user_input = get_user_input(output_dir)
        
        if user_input:
            url, fmt, output_dir, is_playlist, quality_option = user_input
            download_video(url, fmt, read_config(), is_playlist, quality_option)
        else:
            break

if __name__ == "__main__":
    clear_screen()
    main()
