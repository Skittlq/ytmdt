"""Utility script to fetch yt-dlp.exe and ffmpeg zip into ytmdt-dependencies.

Steps performed for each asset:
- Hit the GitHub releases API for the latest release metadata.
- Pick the asset by exact filename or substring (no hardcoded versions).
- Stream the browser_download_url to disk under ./ytmdt-dependencies.
- Verify the downloaded byte count matches the asset size from the API.
"""

from __future__ import annotations

import configparser
import json
import shutil
import sys
import zipfile
import tkinter as tk
import threading
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Callable, Dict
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
import subprocess


CHUNK_SIZE = 1024 * 1024  # 1 MiB chunks for streaming downloads
USER_AGENT = "ytmdt-downloader"
LOG_PATH = Path(__file__).resolve().parent / "log.txt"
CONFIG_PATH = Path(__file__).resolve().parent / "config.ini"


def log(message: str) -> None:
	"""Print to console and append to log file."""

	print(message)
	with LOG_PATH.open("a", encoding="utf-8") as fh:
		fh.write(message + "\n")


def load_config() -> Dict:
	"""Load user settings from config.ini."""
	defaults = {
		"download_folder": str(Path.home() / "Videos" / "YouTube"),
		"quality": "1080p",
		"codec": "vp9",
		"container": "mp4",
		"video_only": "False",
		"allow_playlist": "True",
	}
	
	if not CONFIG_PATH.exists():
		return defaults
	
	config = configparser.ConfigParser()
	try:
		config.read(CONFIG_PATH, encoding="utf-8")
		if "Settings" in config:
			return {key: config["Settings"].get(key, defaults[key]) for key in defaults}
	except Exception as exc:
		log(f"Failed to load config: {exc}")
	
	return defaults


def save_config(settings: Dict) -> None:
	"""Save user settings to config.ini."""
	config = configparser.ConfigParser()
	config["Settings"] = settings
	
	try:
		with CONFIG_PATH.open("w", encoding="utf-8") as fh:
			config.write(fh)
	except Exception as exc:
		log(f"Failed to save config: {exc}")


def fetch_latest_asset(
	api_url: str, *, expected_name: str | None = None, name_contains: str | None = None
) -> Dict:
	"""Return the asset dict matching exact name or substring from the release payload."""

	if expected_name is None and name_contains is None:
		raise ValueError("expected_name or name_contains must be provided")

	req = Request(api_url, headers={"User-Agent": USER_AGENT})
	with urlopen(req) as resp:  # noqa: S310 (standard library URL access)
		payload = json.loads(resp.read().decode("utf-8"))

	assets = payload.get("assets", [])
	partial_match = None
	for asset in assets:
		name = asset.get("name")
		if expected_name and name == expected_name:
			return asset
		if name_contains and name and name_contains in name and partial_match is None:
			partial_match = asset

	if partial_match:
		return partial_match

	raise RuntimeError(
		f"Asset not found in latest release for {api_url} (expected_name={expected_name}, name_contains={name_contains})"
	)


def download_asset(asset: Dict, dest_dir: Path) -> Path:
	dest_dir.mkdir(parents=True, exist_ok=True)
	target = dest_dir / asset["name"]

	req = Request(asset["browser_download_url"], headers={"User-Agent": USER_AGENT})

	expected_size = asset.get("size")

	if target.exists() and expected_size and target.stat().st_size == expected_size:
		log(f"Already present and size matches: {target}")
		return target

	try:
		with urlopen(req) as resp:  # noqa: S310
			size_header = resp.headers.get("Content-Length")
			expected_size = int(size_header) if size_header else expected_size
			written = 0

			with target.open("wb") as fh:
				while True:
					chunk = resp.read(CHUNK_SIZE)
					if not chunk:
						break
					fh.write(chunk)
					written += len(chunk)

		if expected_size and written != expected_size:
			raise RuntimeError(
				f"Size mismatch for {target.name}: expected {expected_size} bytes, wrote {written} bytes"
			)

		return target
	except (HTTPError, URLError) as exc:  # pragma: no cover - network failure handling
		raise RuntimeError(f"Download failed for {asset.get('name')}: {exc}") from exc


def ensure_ffmpeg_unpacked(zip_path: Path, dest_dir: Path) -> Path:
	"""Extract ffmpeg zip into dest_dir/ffmpeg unless already unpacked."""

	output = dest_dir
	extracted_root = output / zip_path.stem
	ffmpeg_exe = extracted_root / "bin" / "ffmpeg.exe"

	def cleanup_old_ffmpeg_dirs() -> None:
		"""Remove older ffmpeg extract folders to avoid piling up versions."""
		prefix = "ffmpeg"
		for candidate in output.iterdir():
			if not candidate.is_dir():
				continue
			if candidate == extracted_root:
				continue
			name = candidate.name.lower()
			if name.startswith(prefix):
				try:
					shutil.rmtree(candidate)
					log(f"Removed old ffmpeg folder: {candidate.name}")
				except Exception as exc:
					log(f"Failed to remove {candidate.name}: {exc}")

	if ffmpeg_exe.exists():
		log(f"ffmpeg already unpacked at {extracted_root}")
		cleanup_old_ffmpeg_dirs()
		return extracted_root

	log(f"Extracting {zip_path.name} to {output} ...")
	output.mkdir(parents=True, exist_ok=True)

	with zipfile.ZipFile(zip_path, "r") as zf:
		zf.extractall(output)

	if not ffmpeg_exe.exists():
		raise RuntimeError(f"ffmpeg.exe not found after extraction in {output}")

	log(f"Extracted ffmpeg to {extracted_root}")
	cleanup_old_ffmpeg_dirs()
	return extracted_root


def launch_ui() -> None:
	"""Launch the Tkinter UI for the downloader."""

	root = tk.Tk()
	root.title("YTMDT")
	icon_path = Path(__file__).resolve().parent / "DownloadYouTube.ico"
	if icon_path.exists():
		root.iconbitmap(default=str(icon_path))
	root.geometry("720x520")
	root.minsize(640, 480)

	# Load saved settings
	config = load_config()
	default_folder = Path(config["download_folder"])
	default_folder_str = str(default_folder)

	# Codec display mapping
	CODEC_DISPLAY = {"vp9": "Better Quality (vp9)", "avc1": "Better Compatibility (avc1)"}
	CODEC_ACTUAL = {"Better Quality (vp9)": "vp9", "Better Compatibility (avc1)": "avc1"}

	def get_actual_codec(display: str) -> str:
		"""Convert display name to actual codec value."""
		return CODEC_ACTUAL.get(display, display)

	# Create variables that will be used by save_settings
	download_var = tk.StringVar(value=default_folder_str)
	codec_display = CODEC_DISPLAY.get(config["codec"], config["codec"])
	quality_var = tk.StringVar(value=config["quality"])
	codec_var = tk.StringVar(value=codec_display)
	container_var = tk.StringVar(value=config["container"])
	video_only_var = tk.BooleanVar(value=config["video_only"] == "True")
	playlist_var = tk.BooleanVar(value=config["allow_playlist"] == "True")

	def save_settings() -> None:
		"""Save current UI settings to config file."""
		settings = {
			"download_folder": download_var.get(),
			"quality": quality_var.get(),
			"codec": get_actual_codec(codec_var.get()),
			"container": container_var.get(),
			"video_only": str(video_only_var.get()),
			"allow_playlist": str(playlist_var.get()),
		}
		save_config(settings)

	def pick_folder() -> None:
		selected = filedialog.askdirectory(title="Select download folder")
		if selected:
			download_var.set(selected)
			save_settings()

	def build_format_string(quality: str, codec: str, container: str, video_only: bool) -> str:
		codec = get_actual_codec(codec)
		audio_formats = {"mp3", "m4a", "wav", "opus"}
		if container in audio_formats:
			return "bestaudio/best"
		# Map label to max height.
		max_height = quality.replace("p", "")
		if video_only:
			# Video without audio
			return (
				f"bestvideo[height<={max_height}][vcodec*={codec}]/"
				f"bestvideo[height<={max_height}]/best"
			)
		# Prefer selected codec; if unavailable, allow fallback.
		return (
			f"bestvideo[height<={max_height}][vcodec*={codec}]+bestaudio/"
			f"bestvideo[height<={max_height}]+bestaudio/best"
		)

	def build_output_template(folder: Path, container: str) -> str:
		# Use yt-dlp output template for consistent naming.
		ext = container if container else "%(ext)s"
		return str(folder / f"%(title)s [%(id)s].{ext}")

	def preview_download() -> None:
		"""Show download preview with size and video count in the UI."""
		url = url_var.get().strip()
		if not url:
			preview_var.set("Paste a YouTube URL to see download info")
			download_btn.config(state=tk.DISABLED)
			return

		quality = quality_var.get()
		codec = codec_var.get()
		container = container_var.get()
		video_only = video_only_var.get()
		allow_playlist = playlist_var.get()

		format_string = build_format_string(quality, codec, container, video_only)

		# Build yt-dlp command to get file sizes
		cmd = [str(Path(__file__).resolve().parent / "ytmdt-dependencies" / "yt-dlp.exe")]
		if not Path(cmd[0]).exists():
			cmd = ["yt-dlp"]

		cmd += ["-f", format_string, "--print", "filesize_approx", "--skip-download"]
		if not allow_playlist:
			cmd += ["--no-playlist"]
		cmd.append(url)

		preview_var.set("Calculating size...")
		download_btn.config(state=tk.DISABLED)

		def worker() -> None:
			try:
				creationflags = 0
				if sys.platform.startswith("win"):
					creationflags = subprocess.CREATE_NO_WINDOW
				process = subprocess.Popen(
					cmd,
					stdout=subprocess.PIPE,
					stderr=subprocess.STDOUT,
					text=True,
					bufsize=1,
					universal_newlines=True,
					creationflags=creationflags,
				)
				sizes = []
				for line in process.stdout:
					line = line.strip()
					if line and line != "NA":
						try:
							sizes.append(int(line))
						except ValueError:
							pass
				process.wait()

				if process.returncode == 0 and sizes:
					total_bytes = sum(sizes)
					num_videos = len(sizes)
					
					# Format size nicely
					if total_bytes >= 1024 * 1024 * 1024:
						size_str = f"{total_bytes / (1024 * 1024 * 1024):.2f} GB"
					elif total_bytes >= 1024 * 1024:
						size_str = f"{total_bytes / (1024 * 1024):.2f} MB"
					else:
						size_str = f"{total_bytes / 1024:.2f} KB"
					
					if num_videos == 1:
						msg = f"Ready to download: 1 video, {size_str}"
					else:
						msg = f"Ready to download: {num_videos} videos, {size_str} total"
					
					root.after(0, lambda: (preview_var.set(msg), download_btn.config(state=tk.NORMAL)))
				else:
					root.after(0, lambda: (preview_var.set("Size info unavailable, but ready to download"), download_btn.config(state=tk.NORMAL)))
			except Exception as exc:
				log(f"Preview error: {exc}")
				root.after(0, lambda: (preview_var.set("Preview failed, but you can still download"), download_btn.config(state=tk.NORMAL)))

		threading.Thread(target=worker, daemon=True).start()

	def run_download() -> None:
		url = url_var.get().strip()
		if not url:
			messagebox.showerror("Missing URL", "Please enter a YouTube URL.")
			return

		folder = Path(download_var.get().strip() or default_folder_str)
		folder.mkdir(parents=True, exist_ok=True)

		quality = quality_var.get()
		codec = codec_var.get()
		container = container_var.get()
		video_only = video_only_var.get()
		allow_playlist = playlist_var.get()

		format_string = build_format_string(quality, codec, container, video_only)
		output_template = build_output_template(folder, container)

		cmd = [str(Path(__file__).resolve().parent / "ytmdt-dependencies" / "yt-dlp.exe")]
		if not Path(cmd[0]).exists():
			cmd = ["yt-dlp"]

		cmd += ["-f", format_string, "-o", output_template]
		audio_formats = {"mp3", "m4a", "wav", "opus"}
		if container in audio_formats:
			cmd += ["-x", "--audio-format", container]
		elif container and not video_only:
			cmd += ["--merge-output-format", container]
		if not allow_playlist:
			cmd += ["--no-playlist"]

		cmd.append(url)

		# Track downloaded files
		downloaded_files = []

		def update_progress(percent: float, info: str) -> None:
			"""Update progress bar and info label."""
			progress_bar["value"] = percent
			progress_info_var.set(info)

		def parse_progress_line(line: str) -> tuple[float, str] | None:
			"""Extract percentage and info from yt-dlp output."""
			import re
			# Track destination files
			if "[download] Destination:" in line:
				parts = line.split("[download] Destination:", 1)
				if len(parts) == 2:
					file_path = Path(parts[1].strip())
					if file_path not in downloaded_files:
						downloaded_files.append(file_path)
			# Match lines like: [download]  45.2% of 123.45MiB at 5.67MiB/s ETA 00:12
			match = re.search(r"\[download\]\s+(\d+\.\d+)%.*?at\s+([\d.]+\w+/s)", line)
			if match:
				percent = float(match.group(1))
				speed = match.group(2)
				return percent, f"{percent:.1f}% at {speed}"
			# Match percentage without speed
			match = re.search(r"\[download\]\s+(\d+\.\d+)%", line)
			if match:
				percent = float(match.group(1))
				return percent, f"{percent:.1f}%"
			return None

		def worker() -> None:
			log("Running: " + " ".join(cmd))
			root.after(0, lambda: update_progress(0, "Starting download..."))
			try:
				creationflags = 0
				if sys.platform.startswith("win"):
					creationflags = subprocess.CREATE_NO_WINDOW
				process = subprocess.Popen(
					cmd,
					stdout=subprocess.PIPE,
					stderr=subprocess.STDOUT,
					text=True,
					bufsize=1,
					universal_newlines=True,
					creationflags=creationflags,
				)
				for line in process.stdout:
					log(line.rstrip())
					progress_data = parse_progress_line(line)
					if progress_data:
						percent, info = progress_data
						root.after(0, lambda p=percent, i=info: update_progress(p, i))
					else:
						# Show other status messages
						line_stripped = line.strip()
						if line_stripped and not line_stripped.startswith("[download]"):
							root.after(0, lambda l=line_stripped: progress_info_var.set(l[:80]))
				process.wait()
				if process.returncode == 0:
					root.after(0, lambda: on_download_finished(True, folder, downloaded_files))
				else:
					root.after(0, lambda: on_download_finished(False, folder, []))
			except Exception as exc:
				log(f"Error: {exc}")
				root.after(0, lambda e=str(exc): progress_info_var.set(f"Error: {e}"))
				root.after(0, lambda: on_download_finished(False, folder, []))

		def on_download_finished(success: bool, folder: Path, files: list) -> None:
			download_btn.config(state=tk.NORMAL)
			status_var.set("Idle")
			if success:
				update_progress(100, "Download completed successfully!")
				show_completion_dialog(folder, files)
			else:
				progress_info_var.set("Download failed. See log.txt for details.")
				messagebox.showerror("Download failed", "yt-dlp reported an error. See log.txt for details.")

		def show_completion_dialog(folder: Path, files: list) -> None:
			"""Show custom completion dialog with options."""
			dialog = tk.Toplevel(root)
			dialog.title("Download Complete")
			dialog.geometry("400x150")
			dialog.resizable(False, False)
			dialog.transient(root)
			dialog.grab_set()
			
			msg_frame = ttk.Frame(dialog, padding=20)
			msg_frame.pack(fill=tk.BOTH, expand=True)
			
			if len(files) == 1:
				msg = "Download completed successfully!"
			elif len(files) > 1:
				msg = f"Downloaded {len(files)} videos successfully!"
			else:
				msg = "Download completed!"
			
			ttk.Label(msg_frame, text=msg, font=("Segoe UI", 10)).pack(pady=(0, 20))
			
			button_frame = ttk.Frame(msg_frame)
			button_frame.pack()
			
			def open_folder() -> None:
				import os
				os.startfile(folder)
				dialog.destroy()
			
			def open_video() -> None:
				import os
				if files:
					# Find the first existing file
					for f in files:
						if f.exists():
							os.startfile(f)
							break
				dialog.destroy()
			
			ttk.Button(button_frame, text="Open Folder", command=open_folder).pack(side=tk.LEFT, padx=5)
			if len(files) == 1:
				ttk.Button(button_frame, text="Open Video", command=open_video).pack(side=tk.LEFT, padx=5)
			ttk.Button(button_frame, text="Close", command=dialog.destroy).pack(side=tk.LEFT, padx=5)
			
			# Center dialog on parent
			dialog.update_idletasks()
			x = root.winfo_x() + (root.winfo_width() // 2) - (dialog.winfo_width() // 2)
			y = root.winfo_y() + (root.winfo_height() // 2) - (dialog.winfo_height() // 2)
			dialog.geometry(f"+{x}+{y}")

		# Reset progress
		
		download_btn.config(state=tk.DISABLED)
		status_var.set("Downloading...")
		threading.Thread(target=worker, daemon=True).start()

	main = ttk.Frame(root, padding=16)
	main.pack(fill=tk.BOTH, expand=True)

	title = ttk.Label(main, text="YouTube Media Downloader Tool", font=("Segoe UI", 14, "bold"))
	title.pack(anchor="w")

	url_label = ttk.Label(main, text="YouTube URL (video or playlist)")
	url_label.pack(anchor="w", pady=(12, 4))
	url_var = tk.StringVar()
	url_entry = ttk.Entry(main, textvariable=url_var)
	url_entry.pack(fill=tk.X)

	def on_url_change(*args) -> None:
		"""Auto-trigger preview when YouTube URL is pasted."""
		url = url_var.get().strip()
		# Check if it looks like a YouTube URL
		if url and ("youtube.com" in url or "youtu.be" in url):
			# Schedule preview to run after a short delay
			root.after(500, preview_download)
		else:
			preview_var.set("Paste a YouTube URL to see download info")
			download_btn.config(state=tk.DISABLED)

	url_var.trace_add("write", on_url_change)

	folder_label = ttk.Label(main, text="Download folder")
	folder_label.pack(anchor="w", pady=(12, 4))
	folder_row = ttk.Frame(main)
	folder_row.pack(fill=tk.X)
	default_note = f"Default: {default_folder_str}"
	folder_entry = ttk.Entry(folder_row, textvariable=download_var)
	folder_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)
	folder_btn = ttk.Button(folder_row, text="Browse", command=pick_folder)
	folder_btn.pack(side=tk.LEFT, padx=(8, 0))

	options = ttk.Frame(main)
	options.pack(fill=tk.X, pady=(16, 0))

	quality_label = ttk.Label(options, text="Video quality")
	quality_label.grid(row=0, column=0, sticky="w")
	quality_box = ttk.Combobox(
		options,
		textvariable=quality_var,
		values=["144p", "240p", "360p", "480p", "720p", "1080p", "1440p", "2160p"],
		state="readonly",
	)
	quality_box.grid(row=1, column=0, sticky="we", padx=(0, 12))
	quality_box.bind("<<ComboboxSelected>>", lambda e: save_settings())

	codec_label = ttk.Label(options, text="Video codec")
	codec_label.grid(row=0, column=1, sticky="w")
	codec_box = ttk.Combobox(options, textvariable=codec_var, values=list(CODEC_DISPLAY.values()), state="readonly")
	codec_box.grid(row=1, column=1, sticky="we")
	codec_box.bind("<<ComboboxSelected>>", lambda e: save_settings())

	options.columnconfigure(0, weight=1)
	options.columnconfigure(1, weight=1)

	container_row = ttk.Frame(main)
	container_row.pack(fill=tk.X, pady=(12, 0))
	container_label = ttk.Label(container_row, text="Output container")
	container_label.pack(anchor="w")
	container_box = ttk.Combobox(
		container_row,
		textvariable=container_var,
		values=["mp4", "mkv", "webm", "mp3", "m4a", "wav", "opus"],
		state="readonly",
	)
	container_box.pack(anchor="w", pady=(4, 0))
	container_box.bind("<<ComboboxSelected>>", lambda e: save_settings())

	video_only_check = ttk.Checkbutton(
		main,
		text="Download video without audio",
		variable=video_only_var,
		command=save_settings,
	)
	video_only_check.pack(anchor="w", pady=(12, 0))

	playlist_check = ttk.Checkbutton(
		main,
		text="Allow playlist downloads (uncheck to force single video)",
		variable=playlist_var,
		command=save_settings,
	)
	playlist_check.pack(anchor="w", pady=(8, 0))

	# Preview info display
	preview_var = tk.StringVar(value="Paste a YouTube URL to see download info")
	preview_label = ttk.Label(main, textvariable=preview_var, foreground="#0066cc")
	preview_label.pack(anchor="w", pady=(8, 8))

	# Progress display
	progress_label = ttk.Label(main, text="Download progress")
	progress_label.pack(anchor="w", pady=(8, 4))
	progress_bar = ttk.Progressbar(main, length=400, mode="determinate", maximum=100)
	progress_bar.pack(fill=tk.X, pady=(0, 8))
	progress_info_var = tk.StringVar(value="Ready")
	progress_info_label = ttk.Label(main, textvariable=progress_info_var)
	progress_info_label.pack(anchor="w", pady=(0, 8))

	button_row = ttk.Frame(main)
	button_row.pack(fill=tk.X, pady=(8, 0))
	download_btn = ttk.Button(button_row, text="Download", command=run_download, state=tk.DISABLED)
	download_btn.pack(side=tk.LEFT)
	quit_btn = ttk.Button(button_row, text="Quit", command=root.destroy)
	quit_btn.pack(side=tk.RIGHT)

	status_var = tk.StringVar(value="Idle")
	status_label = ttk.Label(main, textvariable=status_var)
	status_label.pack(anchor="w", pady=(12, 0))

	url_entry.focus()
	root.mainloop()


def download_dependencies(status_callback: Callable[[str], None] | None = None) -> None:
	"""Download yt-dlp/ffmpeg dependencies with optional status updates."""
	dest = Path(__file__).resolve().parent / "ytmdt-dependencies"

	def report(message: str) -> None:
		log(message)
		if status_callback:
			status_callback(message)

	jobs = [
		{
			"api": "https://api.github.com/repos/yt-dlp/yt-dlp/releases/latest",
			"expected_name": "yt-dlp.exe",
		},
		{
			"api": "https://api.github.com/repos/GyanD/codexffmpeg/releases/latest",
			"name_contains": "essentials_build.zip",
		},
	]

	report("Preparing dependencies (yt-dlp and ffmpeg) ...")
	for job in jobs:
		report(f"Fetching metadata for {job.get('expected_name') or job.get('name_contains')} ...")
		asset = fetch_latest_asset(
			job["api"], expected_name=job.get("expected_name"), name_contains=job.get("name_contains")
		)
		report(f"Downloading {asset['name']} ...")
		path = download_asset(asset, dest)
		report(f"Downloaded and verified: {path.name}")

		if "ffmpeg" in asset["name"] and path.suffix == ".zip":
			report("Extracting ffmpeg ...")
			ensure_ffmpeg_unpacked(path, dest)


def main() -> None:
	startup = tk.Tk()
	startup.title("YTMDT")
	icon_path = Path(__file__).resolve().parent / "DownloadYouTube.ico"
	if icon_path.exists():
		startup.iconbitmap(default=str(icon_path))
	startup.geometry("480x160")
	startup.resizable(False, False)

	startup_frame = ttk.Frame(startup, padding=16)
	startup_frame.pack(fill=tk.BOTH, expand=True)

	status_var = tk.StringVar(value="Preparing dependencies...")
	status_label = ttk.Label(startup_frame, textvariable=status_var, wraplength=440)
	status_label.pack(anchor="w", pady=(0, 12))

	progress = ttk.Progressbar(startup_frame, mode="indeterminate")
	progress.pack(fill=tk.X)
	progress.start(10)

	def set_status(message: str) -> None:
		startup.after(0, lambda m=message: status_var.set(m))

	def finish(success: bool, error_message: str | None) -> None:
		progress.stop()
		if success:
			startup.destroy()
			launch_ui()
			return

		messagebox.showerror(
			"Startup error",
			"Failed to prepare dependencies. See log.txt for details.\n\n" + (error_message or "Unknown error"),
			parent=startup,
		)
		startup.destroy()
		sys.exit(1)

	def worker() -> None:
		try:
			download_dependencies(status_callback=set_status)
			startup.after(0, lambda: finish(True, None))
		except Exception as exc:
			log(f"Startup error: {exc}")
			startup.after(0, lambda e=str(exc): finish(False, e))

	threading.Thread(target=worker, daemon=True).start()
	startup.mainloop()


if __name__ == "__main__":
	try:
		main()
	except Exception as exc:  # pragma: no cover - top-level error reporting
		log(f"Error: {exc}")
		print(f"Error: {exc}", file=sys.stderr)
		sys.exit(1)
