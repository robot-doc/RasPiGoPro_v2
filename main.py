#!/usr/bin/env python3
"""
Main entry point for Dual WiFi Interface GoPro Controller
"""

import asyncio
import logging

from dual_wifi_manager import DualWiFiGoProManager

logger = logging.getLogger(__name__)

class GoProControllerUI:
    """User interface for the GoPro controller"""
    
    def __init__(self):
        self.manager = DualWiFiGoProManager()
    
    async def control_camera_bluetooth(self, camera_id: str):
        """Control individual camera via Bluetooth"""
        if camera_id not in self.manager.cameras:
            print("❌ Camera not available")
            return
        
        camera = self.manager.cameras[camera_id]
                
        while True:
            print(f"\n🎮 {camera.camera_name} - Bluetooth Control")
            print("1. Take photo")
            print("2. Start recording")
            print("3. Stop recording")
            print("4. Enable WiFi")
            print("0. Back")
            
            choice = input("Choice: ").strip()
            
            if choice == '1':
                if await camera.take_photo_bt():
                    print("📸 Photo taken!")
                else:
                    print("❌ Failed")
            
            elif choice == '2':
                if await camera.start_recording_bt():
                    print("🎬 Recording started!")
                else:
                    print("❌ Failed")
            
            elif choice == '3':
                if await camera.stop_recording_bt():
                    print("⏹️ Recording stopped!")
                else:
                    print("❌ Failed")
            
            elif choice == '4':
                if await camera.enable_wifi():
                    print(f"📶 WiFi enabled: {camera.wifi_ssid}")
                else:
                    print("❌ WiFi enable failed")
            
            elif choice == '0':
                break
    
    def control_camera_wifi(self, camera_id: str):
        """Control individual camera via WiFi with enhanced debugging"""
        print(f"\n🎮 WiFi Control Request for: {camera_id}")
        
        if camera_id not in self.manager.wifi_controllers:
            print("❌ WiFi not connected to this camera")
            print("💡 Use option 31 or 32 to connect WiFi first")
            print(f"📋 Available WiFi controllers: {list(self.manager.wifi_controllers.keys())}")
            return
        
        camera = self.manager.cameras[camera_id]
        wifi_ctrl = self.manager.wifi_controllers[camera_id]
        
        print(f"✅ Found WiFi controller for {camera.camera_name}")
        print(f"   Interface: {wifi_ctrl.wifi_interface}")
        print(f"   Interface IP: {wifi_ctrl.interface_ip}")
        
        while True:
            print(f"\n🎮 {camera.camera_name} - WiFi Control")
            print(f"   (via {wifi_ctrl.wifi_interface} at {wifi_ctrl.interface_ip})")
            print("1. Take photo")
            print("2. Start recording")
            print("3. Stop recording")
            print("4. Get status")
            print("5. Test connection")
            print("0. Back")
            
            choice = input("Choice: ").strip()
            
            if choice == '1':
                print(f"\n📸 Taking photo on {camera.camera_name}...")
                if wifi_ctrl.take_photo():
                    print("✅ Photo command sent!")
                else:
                    print("❌ Photo command failed")
            
            elif choice == '2':
                print(f"\n🎬 Starting recording on {camera.camera_name}...")
                if wifi_ctrl.start_recording():
                    print("✅ Recording started!")
                else:
                    print("❌ Recording start failed")
            
            elif choice == '3':
                print(f"\n⏹️ Stopping recording on {camera.camera_name}...")
                if wifi_ctrl.stop_recording():
                    print("✅ Recording stopped!")
                else:
                    print("❌ Recording stop failed")
            
            elif choice == '4':
                print(f"\n📊 Getting status from {camera.camera_name}...")
                status = wifi_ctrl.get_status()
                if status:
                    battery = status.get('status', {}).get('70', 'Unknown')
                    recording = status.get('status', {}).get('8', 0)
                    mode = status.get('status', {}).get('43', 'Unknown')
                    print(f"🔋 Battery: {battery}%")
                    print(f"🔴 Recording: {'Yes' if recording else 'No'}")
                    print(f"📷 Mode: {mode}")
                else:
                    print("❌ No status received")
            
            elif choice == '5':
                print(f"\n🔍 Testing connection to {camera.camera_name}...")
                if wifi_ctrl.test_connection():
                    print("✅ Connection test passed!")
                else:
                    print("❌ Connection test failed")
            
            elif choice == '0':
                break
    
    async def simultaneous_control(self):
        """Control multiple cameras simultaneously"""
        if len(self.manager.cameras) < 2:
            print("❌ Need at least 2 cameras for simultaneous control")
            return
        
        while True:
            print(f"\n🎮 Simultaneous Control - {len(self.manager.cameras)} Cameras")
            print("1. Take photos on ALL cameras")
            print("2. Start recording on ALL cameras")
            print("3. Stop recording on ALL cameras")
            print("4. Enable WiFi on ALL cameras")
            print("0. Back")
            
            choice = input("Choice: ").strip()
            
            if choice == '1':
                print("📸 Taking photos on all cameras...")
                tasks = [camera.take_photo_bt() for camera in self.manager.cameras.values()]
                results = await asyncio.gather(*tasks)
                success_count = sum(results)
                print(f"✅ {success_count}/{len(self.manager.cameras)} photos taken")
            
            elif choice == '2':
                print("🎬 Starting recording on all cameras...")
                tasks = [camera.start_recording_bt() for camera in self.manager.cameras.values()]
                results = await asyncio.gather(*tasks)
                success_count = sum(results)
                print(f"✅ {success_count}/{len(self.manager.cameras)} cameras recording")
            
            elif choice == '3':
                print("⏹️ Stopping recording on all cameras...")
                tasks = [camera.stop_recording_bt() for camera in self.manager.cameras.values()]
                results = await asyncio.gather(*tasks)
                success_count = sum(results)
                print(f"✅ {success_count}/{len(self.manager.cameras)} cameras stopped")
            
            elif choice == '4':
                print("📶 Enabling WiFi on all cameras...")
                tasks = [camera.enable_wifi() for camera in self.manager.cameras.values()]
                results = await asyncio.gather(*tasks)
                success_count = sum(results)
                print(f"✅ {success_count}/{len(self.manager.cameras)} WiFi enabled")
            
            elif choice == '0':
                break
    
    def show_main_menu(self):
        """Display the main menu"""
        camera_list = list(self.manager.cameras.items())
        
        print(f"\n🎯 Main Menu - {len(self.manager.cameras)} Cameras Connected")
        print("-" * 60)
        
        # List available cameras with interface assignments
        for i, (camera_id, camera) in enumerate(camera_list, 1):
            bt_status = "🔗 BT" if camera.connected else "❌"
            wifi_status = "📶 WiFi" if camera_id in self.manager.wifi_controllers else ""
            print(f"{i}. {camera.camera_name} {bt_status} {wifi_status} [{camera_id}]")
        
        print()
        print("Individual Control:")
        for i, (camera_id, camera) in enumerate(camera_list, 1):
            print(f"{i+10}. Control {camera.camera_name} (Bluetooth)")
            print(f"{i+20}. Control {camera.camera_name} (WiFi)")
            print(f"{i+30}. Connect {camera.camera_name} WiFi")
        
        print()
        print("Multi-Camera Control:")
        print("90. Simultaneous control (All cameras)")
        print("91. Enable WiFi on all cameras")
        print("92. Add new camera")
        print("93. Show configuration")
        print("94. Network debug info")
        print("95. WiFi controller debug")
        print("0. Exit")
    
    async def handle_menu_choice(self, choice: str):
        """Handle user menu choice"""
        camera_list = list(self.manager.cameras.items())
        
        if choice == '0':
            return False  # Exit
        
        elif choice == '90':
            await self.simultaneous_control()
        
        elif choice == '91':
            print("📶 Enabling WiFi on all cameras...")
            for camera in self.manager.cameras.values():
                await camera.enable_wifi()
        
        elif choice == '92':
            await self.manager.discover_and_pair_cameras()
        
        elif choice == '93':
            self.manager.show_config_status()
        
        elif choice == '94':
            self.manager.show_network_debug()
        
        elif choice == '95':
            self.manager.show_wifi_controller_debug()
        
        else:
            try:
                choice_num = int(choice)
                
                # Bluetooth control (11-19)
                if 11 <= choice_num <= 19:
                    camera_index = choice_num - 11
                    if camera_index < len(camera_list):
                        camera_id, camera = camera_list[camera_index]
                        await self.control_camera_bluetooth(camera_id)
                    else:
                        print(f"❌ Camera {camera_index + 1} not available")
                
                # WiFi control (21-29)
                elif 21 <= choice_num <= 29:
                    camera_index = choice_num - 21
                    if camera_index < len(camera_list):
                        camera_id, camera = camera_list[camera_index]
                        self.control_camera_wifi(camera_id)
                    else:
                        print(f"❌ Camera {camera_index + 1} not available")
                
                # WiFi connection (31-39)
                elif 31 <= choice_num <= 39:
                    camera_index = choice_num - 31
                    if camera_index < len(camera_list):
                        camera_id, camera = camera_list[camera_index]
                        self.manager.connect_to_wifi_interface(camera_id)
                    else:
                        print(f"❌ Camera {camera_index + 1} not available")
                
                else:
                    print("Invalid choice")
                    
            except ValueError:
                print("Invalid choice")
        
        return True  # Continue running
    
    async def run(self):
        """Main application loop"""
        print("🚀 Dual WiFi Interface GoPro Controller")
        print("📱 Camera 1 (GoPro 3811) → wlan0")
        print("📱 Camera 2 (TBD) → wlan1")
        print("=" * 50)
        
        self.manager.show_config_status()
        
        try:
            # Step 1: Connect to cameras
            print("\n📶 Step 1: Camera Connection")
            
            # Try known cameras first
            if not await self.manager.connect_known_cameras():
                print("🔍 No known cameras found, starting discovery...")
                if not await self.manager.discover_and_pair_cameras():
                    print("❌ No cameras available")
                    return
            
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
            print("\n👋 All cameras disconnected!")

async def main():
    """Main entry point"""
    app = GoProControllerUI()
    await app.run()
31

if __name__ == "__main__":
    print("🎬 Dual WiFi Interface GoPro Controller")
    print("📋 Camera 1 → wlan0 (built-in WiFi)")
    print("📋 Camera 2 → wlan1 (USB WiFi adapter)")
    print("🔄 Automatic interface assignment and management")
    print()
    
    asyncio.run(main())