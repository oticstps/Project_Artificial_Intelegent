=======================================================================
                            README-vnc
                          Linux for Tegra
               Configuring VNC from the command-line
=======================================================================

A VNC server allows access to the graphical display of a Linux for Tegra system
over the network. This allows you to work physically remote from the Linux for
Tegra system, and avoids the need to connect an HDMI display, USB keyboard, or
mouse.

All commands specified below should be executed from a terminal on the Linux
for Tegra system. This could be a serial port, an SSH session, or a graphical
terminal application running on the HDMI display.

----------------------------------------------------------------------
Installing the VNC Server
----------------------------------------------------------------------

It is expected that the VNC server software is pre-installed. Execute the
following commands to ensure that it is:

sudo apt update
sudo apt install vino

----------------------------------------------------------------------
Enabling the VNC Server
----------------------------------------------------------------------

Execute the following commands to enable the VNC server:

# Enable the VNC server to start each time you log in
mkdir -p ~/.config/autostart
cp /usr/share/applications/vino-server.desktop ~/.config/autostart

# Configure the VNC server
gsettings set org.gnome.Vino prompt-enabled false
gsettings set org.gnome.Vino require-encryption false

# Set a password to access the VNC server
# Replace thepassword with your desired password
gsettings set org.gnome.Vino authentication-methods "['vnc']"
gsettings set org.gnome.Vino vnc-password $(echo -n 'thepassword'|base64)

# Reboot the system so that the settings take effect
sudo reboot

The VNC server is only available after you have logged in to Jetson locally. If
you wish VNC to be available automatically, use the system settings application
to enable automatic login.

----------------------------------------------------------------------
Connecting to the VNC server
----------------------------------------------------------------------

Use any standard VNC client application to connect to the VNC server that is
running on Linux for Tegra. Popular examples for Linux are gvncviewer and
remmina. Use your own favorite client for Windows or MacOS.

To connect, you will need to know the IP address of the Linux for Tegra system.
Execute the following command to determine the IP address:

ifconfig

Search the output for the text "inet addr:" followed by a sequence of four
numbers, for the relevant network interface (e.g. eth0 for wired Ethernet,
wlan0 for WiFi, or l4tbr0 for the USB device mode Ethernet connection).

----------------------------------------------------------------------
Setting the Desktop Resolution
----------------------------------------------------------------------

The desktop resolution is typically determined by the capabilities of the
display that is attached to Jetson. If no display is attached, a default
resolution of 640x480 is selected. To use a different resolution, edit
/etc/X11/xorg.conf and append the following lines:

Section "Screen"
   Identifier    "Default Screen"
   Monitor       "Configured Monitor"
   Device        "Tegra0"
   SubSection "Display"
       Depth    24
       Virtual 1280 800 # Modify the resolution by editing these values
   EndSubSection
EndSection
