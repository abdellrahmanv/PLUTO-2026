# How to Run the PLUTO Test Website on Raspberry Pi

This guide provides the quick command to run the operator dashboard on your Raspberry Pi so it can be accessed over the local network via the Pi's IP address.

## Run Command

Run the following command in the terminal on your Raspberry Pi:

```bash
/home/pi/yolo/env/bin/python -m pluto_runtime.web_shell --host 0.0.0.0 --port 8080
```

*Note: If you want to run it without the camera stream initialized (e.g., if the USB camera is disconnected), append the `--camera-disabled` flag:*

```bash
/home/pi/yolo/env/bin/python -m pluto_runtime.web_shell --host 0.0.0.0 --port 8080 --camera-disabled
```

## How to Access the Website

Once the command is running:
1. Find the IP address of your Raspberry Pi (e.g., by running `hostname -I` in the terminal).
2. Open a web browser on any device (computer, phone, or tablet) connected to the same Wi-Fi network.
3. Go to:
   ```text
   http://<RASPBERRY_PI_IP>:8080
   ```
   *(For example: `http://192.168.1.15:8080`)*
