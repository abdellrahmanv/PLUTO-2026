import os
import sys

def compress_video(input_path, output_path, target_size_mb):
    if not os.path.exists(input_path):
        print(f"Error: Input file does not exist at: {input_path}")
        return

    # Check input size
    input_size_bytes = os.path.getsize(input_path)
    input_size_mb = input_size_bytes / (1024 * 1024)
    print(f"Loading video from: {input_path}")
    print(f"Original File Size: {input_size_mb:.2f} MB")

    if target_size_mb >= input_size_mb:
        print(f"Warning: Target size ({target_size_mb} MB) is larger than or equal to the original file size ({input_size_mb:.2f} MB).")
        print("Compression might not be necessary, but proceeding as requested.")

    try:
        from moviepy.editor import VideoFileClip
    except ImportError:
        try:
            from moviepy import VideoFileClip
        except ImportError:
            print("Error: moviepy library is not installed. Please run: pip install moviepy")
            return

    clip = None
    try:
        # Load the video
        clip = VideoFileClip(input_path)
        duration = clip.duration
        
        # Calculate target bitrate
        # 1 MB = 8192 kilobits
        target_total_bitrate_kbps = (target_size_mb * 8192) / duration
        
        # Subtract standard audio bitrate (128 kbps) to get video bitrate
        audio_bitrate_kbps = 128
        video_bitrate_kbps = int(target_total_bitrate_kbps - audio_bitrate_kbps)
        
        # Failsafe: Ensure bitrate doesn't drop to an invalid negative number
        if video_bitrate_kbps < 100:
            print("Warning: The target size is very small for the length of this video. Quality will be highly degraded.")
            video_bitrate_kbps = 100

        print(f"Video Duration: {duration:.2f} seconds")
        print(f"Target Video Bitrate: {video_bitrate_kbps} kbps")
        print("Starting compression... This may take a while depending on your computer's hardware.")

        # Write the compressed file
        clip.write_videofile(
            output_path,
            bitrate=f"{video_bitrate_kbps}k",
            audio_bitrate=f"{audio_bitrate_kbps}k",
            codec="libx264",
            audio_codec="aac"
        )
        
        # Check output size
        if os.path.exists(output_path):
            output_size_bytes = os.path.getsize(output_path)
            output_size_mb = output_size_bytes / (1024 * 1024)
            print(f"\nSuccess! Compressed video saved to: {output_path}")
            print(f"Compressed File Size: {output_size_mb:.2f} MB (Target was: {target_size_mb} MB)")
            reduction = (1 - (output_size_bytes / input_size_bytes)) * 100
            print(f"Size Reduction: {reduction:.1f}%")
        else:
            print("\nError: Compression finished but output file was not created.")

    except Exception as e:
        print(f"An error occurred during video compression: {e}")
    finally:
        if clip is not None:
            clip.close()

if __name__ == "__main__":
    # File paths
    input_file = r"C:\Users\Asus\Downloads\G35.mp4"
    output_file = r"C:\Users\Asus\Downloads\G35_compressed.mp4" 

    # Target size set to 95MB to guarantee it stays under 100MB
    compress_video(input_file, output_file, 95)
