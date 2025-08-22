#!/usr/bin/env python3
"""
Main entry point for Dual WiFi Interface GoPro Controller
Modified to include automatic WiFi connection
"""

import asyncio
import logging

from dual_wifi_manager import DualWiFiGoProManager

logger = logging.getLogger(__name__)

class GoProControllerUI:
    """User interface for the GoPro controller"""
    
    def __init__(self):
        self.manager = DualWiFiGoProManager()
    
    def control_camera_wifi(self, camera_id: str):
        """Control individual camera via WiFi with enhanced debugging"""
        print(f"\n[CTRL] WiFi Control Request for: {camera_id}")
        
        if camera_id not in self.manager.wifi_controllers:
            print("X WiFi not connected to this camera")
            print("[HELP] Use option 91 or 31/32 to connect WiFi first")
            print(f"[CONFIG] Available WiFi controllers: {list(self.manager.wifi_controllers.keys())}")
            return
        
        camera = self.manager.cameras[camera_id]
        wifi_ctrl = self.manager.wifi_controllers[camera_id]
        
        print(f"[OK] Found WiFi controller for {camera.camera_name}")
        print(f"   Interface: {wifi_ctrl.wifi_interface}")
        print(f"   Interface IP: {wifi_ctrl.interface_ip}")
        
        while True:
            print(f"\n[CTRL] {camera.camera_name} - WiFi Control")
            print(f"   (via {wifi_ctrl.wifi_interface} at {wifi_ctrl.interface_ip})")
            print("1. Take photo")
            print("2. Start recording")
            print("3. Stop recording")
            print("4. Get status")
            print("5. Test connection")
            print("0. Back")
            
            choice = input("Choice: ").strip()
            
            if choice == '1':
                print(f"\n[PHOTO] Taking photo on {camera.camera_name}...")
                if wifi_ctrl.take_photo():
                    print("[OK] Photo command sent!")
                else:
                    print("X Photo command failed")
            
            elif choice == '2':
                print(f"\n[REC] Starting recording on {camera.camera_name}...")
                if wifi_ctrl.start_recording():
                    print("[OK] Recording started!")
                else:
                    print("X Recording start failed")
            
            elif choice == '3':
                print(f"\n[STOP] Stopping recording on {camera.camera_name}...")
                if wifi_ctrl.stop_recording():
                    print("[OK] Recording stopped!")
                else:
                    print("X Recording stop failed")
            
            elif choice == '4':
                print(f"\n[STATUS] Getting status from {camera.camera_name}...")
                status = wifi_ctrl.get_status()
                if status:
                    battery = status.get('status', {}).get('70', 'Unknown')
                    recording = status.get('status', {}).get('8', 0)
                    mode = status.get('status', {}).get('43', 'Unknown')
                    print(f"[BATTERY] Battery: {battery}%")
                    print(f"[REC] Recording: {'Yes' if recording else 'No'}")
                    print(f"[MODE] Mode: {mode}")
                else:
                    print("X No status received")
            
            elif choice == '5':
                print(f"\n[CHECK] Testing connection to {camera.camera_name}...")
                if wifi_ctrl.test_connection():
                    print("[OK] Connection test passed!")
                else:
                    print("X Connection test failed")
            
            elif choice == '0':
                break
    
    async def simultaneous_control(self):
        """Control multiple cameras simultaneously"""
        if len(self.manager.cameras) < 2:
            print("X Need at least 2 cameras for simultaneous control")
            return
        
        while True:
            print(f"\n[CTRL] Simultaneous Control - {len(self.manager.cameras)} Cameras")
            print("1. Take photos on ALL cameras")
            print("2. Start recording on ALL cameras")
            print("3. Stop recording on ALL cameras")
            print("4. Enable WiFi on ALL cameras")
            print("0. Back")
            
            choice = input("Choice: ").strip()
            
            if choice == '1':
                print("[PHOTO] Taking photos on all cameras...")
                tasks = [camera.take_photo_bt() for camera in self.manager.cameras.values()]
                results = await asyncio.gather(*tasks)
                success_count = sum(results)
                print(f"[OK] {success_count}/{len(self.manager.cameras)} photos taken")
            
            elif choice == '2':
                print("[REC] Starting recording on all cameras...")
                tasks = [camera.start_recording_bt() for camera in self.manager.cameras.values()]
                results = await asyncio.gather(*tasks)
                success_count = sum(results)
                print(f"[OK] {success_count}/{len(self.manager.cameras)} cameras recording")
            
            elif choice == '3':
                print("[STOP] Stopping recording on all cameras...")
                tasks = [camera.stop_recording_bt() for camera in self.manager.cameras.values()]
                results = await asyncio.gather(*tasks)
                success_count = sum(results)
                print(f"[OK] {success_count}/{len(self.manager.cameras)} cameras stopped")
            
            elif choice == '4':
                print("[WIFI] Enabling WiFi on all cameras...")
                tasks = [camera.enable_wifi() for camera in self.manager.cameras.values()]
                results = await asyncio.gather(*tasks)
                success_count = sum(results)
                print(f"[OK] {success_count}/{len(self.manager.cameras)} WiFi enabled")
            
            elif choice == '0':
                break
    
    def show_main_menu(self):
        """Display the main menu"""
        camera_list = list(self.manager.cameras.items())
        
        print(f"\n[MENU] Main Menu - {len(self.manager.cameras)} Cameras Connected")
        print("-" * 60)
        
        # List available cameras with interface assignments
        for i, (camera_id, camera) in enumerate(camera_list, 1):
            bt_status = "[CONNECT] BT" if camera.connected else "X"
            wifi_status = "[WIFI] WiFi" if camera_id in self.manager.wifi_controllers else ""
            print(f"{i}. {camera.camera_name} {bt_status} {wifi_status} [{camera_id}]")
        
        print()
        print("Individual Control:")
        for i, (camera_id, camera) in enumerate(camera_list, 1):
            # print(f"{i+10}. Control {camera.camera_name} (Bluetooth)")
            print(f"{i+20}. Control {camera.camera_name} (WiFi)")
            print(f"{i+30}. Connect {camera.camera_name} WiFi")
        
        print()
        print("Multi-Camera Control:")
        print("90. Simultaneous control (All cameras)")
        print("91. AUTO: Enable WiFi + Connect ALL cameras")  # NEW AUTO OPTION
        print("92. Add new camera")
        print("93. Show configuration")
        print("94. Network debug info")
        print("95. WiFi controller debug")
        print()
        print("Manual WiFi (Legacy):")
        print("96. Enable WiFi on all cameras (manual)")
        print("0. Exit")
    
    async def handle_menu_choice(self, choice: str):
        """Handle user menu choice"""
        camera_list = list(self.manager.cameras.items())
        
        if choice == '0':
            return False  # Exit
        
        elif choice == '90':
            await self.simultaneous_control()
        
        elif choice == '91':
            # NEW: AUTO WiFi enable and connect
            print("\n[AUTO] Automatic WiFi Enable + Connect All Cameras")
            print("=" * 60)
            await self.manager.auto_enable_all_wifi_and_connect()
            print("=" * 60)
        
        elif choice == '92':
            await self.manager.discover_and_pair_cameras()
        
        elif choice == '93':
            self.manager.show_config_status()
        
        elif choice == '94':
            self.manager.show_network_debug()
        
        elif choice == '95':
            self.manager.show_wifi_controller_debug()
        
        elif choice == '96':
            # Legacy manual WiFi enable
            print("[WIFI] Enabling WiFi on all cameras (manual)...")
            for camera in self.manager.cameras.values():
                await camera.enable_wifi()
        
        else:
            try:
                choice_num = int(choice)

                # WiFi control (21-29)
                #elif 21 <= choice_num <= 29:
                if 21 <= choice_num <= 29:
                    camera_index = choice_num - 21
                    if camera_index < len(camera_list):
                        camera_id, camera = camera_list[camera_index]
                        self.control_camera_wifi(camera_id)
                    else:
                        print(f"X Camera {camera_index + 1} not available")
                
                # WiFi connection (31-39)
                elif 31 <= choice_num <= 39:
                    camera_index = choice_num - 31
                    if camera_index < len(camera_list):
                        camera_id, camera = camera_list[camera_index]
                        self.manager.connect_to_wifi_interface(camera_id)
                    else:
                        print(f"X Camera {camera_index + 1} not available")
                
                else:
                    print("Invalid choice")
                    
            except ValueError:
                print("Invalid choice")
        
        return True  # Continue running
    
    async def run(self):
        """Main application loop"""
        print("[START] Dual WiFi Interface GoPro Controller")
        print("[CAM] Camera 1 (GoPro 3811) -> wlan0")
        print("[CAM] Camera 2 (TBD) -> wlan1")
        print("=" * 50)
        
        self.manager.show_config_status()
        
        try:
            # Step 1: Connect to cameras
            print("\n[WIFI] Step 1: Camera Connection")
            
            # Try known cameras first
            if not await self.manager.connect_known_cameras():
                print("[CHECK] No known cameras found, starting discovery...")
                if not await self.manager.discover_and_pair_cameras():
                    print("X No cameras available")
                    return
            
            # NEW: Offer automatic WiFi setup
            if len(self.manager.cameras) > 0 and len(self.manager.wifi_controllers) == 0:
                print("\n[AUTO] Cameras connected via Bluetooth!")
               
                await self.manager.auto_enable_all_wifi_and_connect()

            
            # Step 2: Main control loop
            while True:
                self.show_main_menu()
                choice = input("\nChoice: ").strip()
                
                if not await self.handle_menu_choice(choice):
                    break
        
        except Exception as e:
            logger.error(f"Error: {e}")
        
        finally:
            await self.manager.disconnect_all()
            print("\n[EXIT] All cameras disconnected!")

async def main():
    """Main entry point"""
    app = GoProControllerUI()
    await app.run()

if __name__ == "__main__":
    print("[REC] Dual WiFi Interface GoPro Controller")
    print("[CONFIG] Camera 1 -> wlan0 (built-in WiFi)")
    print("[CONFIG] Camera 2 -> wlan1 (USB WiFi adapter)")
    print("[AUTO] Automatic interface assignment and management")
    print()
    
    asyncio.run(main())