import os
import re
import shutil
import tkinter as tk
from tkinter import scrolledtext, messagebox, filedialog
import threading
import sys
import subprocess # Import subprocess for running external commands


# Removed prettify_xml as it's no longer used for VMF generation.


def parse_quake_map(map_filepath):
    """
    Parses a Quake .map file to extract brush geometry (planes) and their original texture names.
    It identifies brush blocks within entities and accurately extracts all brush planes,
    ignoring other entity properties like key-value pairs.
    """
    brushes = []          # List to store all parsed brushes, each containing its planes
    current_brush_planes = [] # List to store planes for the current brush being parsed
    
    # State flags to correctly identify entity and brush blocks within the .map file
    in_entity_block = False
    
    try:
        with open(map_filepath, 'r') as f:
            print(f"  Attempting to parse map file: {map_filepath}")
            for line_num, line in enumerate(f, 1):
                stripped_line = line.strip()

                # Skip comments and empty lines for cleaner parsing
                if not stripped_line or stripped_line.startswith('//'):
                    continue

                if stripped_line == '{':
                    if not in_entity_block:
                        # This marks the beginning of a top-level entity (e.g., worldspawn)
                        in_entity_block = True
                        current_brush_planes = [] # Reset for potential new brush
                    else:
                        # This marks the beginning of a brush block within an entity
                        current_brush_planes = [] # Initialize list for planes of this new brush
                elif stripped_line == '}':
                    if current_brush_planes:
                        # End of a brush block, add collected planes to brushes list
                        brushes.append(current_brush_planes)
                        current_brush_planes = [] # Reset for next brush
                    elif in_entity_block:
                        # End of an entity block
                        in_entity_block = False
                else:
                    # If inside an entity block, attempt to parse a plane definition
                    if in_entity_block:
                        # Regex to extract three 3D points and the texture name.
                        # ( x1 y1 z1 ) ( x2 y2 z2 ) ( x3 y3 z3 ) TEXTURE_NAME [ ux uy uz offsetX ] [ vx vy vz offsetY ] rotation scaleX scaleY
                        plane_match = re.match(r'\(\s*([\d\.\-]+)\s+([\d\.\-]+)\s+([\d\.\-]+)\s*\)\s*\(\s*([\d\.\-]+)\s+([\d\.\-]+)\s+([\d\.\-]+)\s*\)\s*\(\s*([\d\.\-]+)\s+([\d\.\-]+)\s+([\d\.\-]+)\s*\)\s*([^\s]+).*', stripped_line)
                        if plane_match:
                            # Extract and convert points to floats
                            p1 = (float(plane_match.group(1)), float(plane_match.group(2)), float(plane_match.group(3)))
                            p2 = (float(plane_match.group(4)), float(plane_match.group(5)), float(plane_match.group(6)))
                            p3 = (float(plane_match.group(7)), float(plane_match.group(8)), float(plane_match.group(9)))
                            texture_name = plane_match.group(10).lower() # Get texture name and convert to lowercase

                            current_brush_planes.append({
                                'plane': (p1, p2, p3),
                                'texture': texture_name # Re-including texture name here
                            })
                        # Lines not matching a plane within a brush block are ignored (e.g., UV/lightmap data or entity properties)
        
        # Add any remaining brush planes if the file ends abruptly without a closing brace
        if current_brush_planes:
            brushes.append(current_brush_planes)

        print(f"  Finished parsing {map_filepath}. Found {len(brushes)} brushes.")
        # We no longer need to return unique_textures separately as they aren't processed for materials
        return brushes
    except FileNotFoundError:
        print(f"[ERROR] Map file not found: {map_filepath}")
        return []
    except Exception as e:
        print(f"[ERROR] An error occurred while parsing {map_filepath}: {e}")
        return []


def generate_vmf_content(map_data):
    """
    Generates the content for a Source 1 .vmf file from the parsed Quake map data.
    This VMF will then be compiled by ResourceCompiler.exe into a Source 2 .vmap.
    Brush faces will be assigned their original Quake texture names.
    Includes a basic info_player_start and empty hidden block for VMF validity.
    """
    vmf_lines = []
    
    # VMF header information
    vmf_lines.append("versioninfo")
    vmf_lines.append("{")
    vmf_lines.append("    \"mapversion\" \"1\"")
    vmf_lines.append("    \"editorversion\" \"400\"")
    vmf_lines.append("    \"editorbuild\" \"8000\"")
    vmf_lines.append("    \"formatversion\" \"1\"")
    vmf_lines.append("    \"prefab\" \"0\"")
    vmf_lines.append("}")

    # Worldspawn entity block
    vmf_lines.append("world")
    vmf_lines.append("{")
    vmf_lines.append("    \"id\" \"1\"") # Worldspawn typically has ID 1
    vmf_lines.append("    \"mapversion\" \"1\"")
    vmf_lines.append("    \"classname\" \"worldspawn\"")

    # Define a scaling factor for Quake units to Source units.
    # The 0.75 scale is intended for the final Alyx map size.
    SCALE_FACTOR = 0.75 
    
    # Unique ID counter for solids (brushes) and sides, starting after worldspawn's ID 1
    current_id = 2 

    # Iterate through each brush parsed from the Quake map
    for brush_idx, brush_planes in enumerate(map_data):
        vmf_lines.append("    solid")
        vmf_lines.append("    {")
        vmf_lines.append(f"        \"id\" \"{current_id}\"")
        current_id += 1

        # Iterate through each plane (side) of the current brush
        for plane_data in brush_planes:
            vmf_lines.append("        side")
            vmf_lines.append("        {")
            vmf_lines.append(f"            \"id\" \"{current_id}\"")
            current_id += 1

            # Quake uses Z-up, Source (1 and 2) typically Y-up.
            # Conversion: (x_quake, y_quake, z_quake) -> (x_source, z_source, -y_source)
            # This is the standard conversion that usually works.
            p1 = plane_data['plane'][0]
            p2 = plane_data['plane'][1]
            p3 = plane_data['plane'][2]

            # Apply Z-up to Y-up conversion and scaling to each point
            p1_s = (p1[0] * SCALE_FACTOR, p1[2] * SCALE_FACTOR, -p1[1] * SCALE_FACTOR)
            p2_s = (p2[0] * SCALE_FACTOR, p2[2] * SCALE_FACTOR, -p2[1] * SCALE_FACTOR)
            p3_s = (p3[0] * SCALE_FACTOR, p3[2] * SCALE_FACTOR, -p3[1] * SCALE_FACTOR)

            # Format coordinates for VMF plane string: "(x1 y1 z1) (x2 y2 z2) (x3 y3 z3)"
            vmf_lines.append(f"            \"plane\" \"({p1_s[0]:.6f} {p1_s[1]:.6f} {p1_s[2]:.6f}) ({p2_s[0]:.6f} {p2_s[1]:.6f} {p2_s[2]:.6f}) ({p3_s[0]:.6f} {p3_s[1]:.6f} {p3_s[2]:.6f})\"")

            # Assign the original Quake texture name, prefixed with "materials/" as expected by Source 1 VMFs.
            # Hammer will then look for a .vmat with this name (e.g., 'materials/wall_tex.vmat')
            vmf_lines.append(f"            \"material\" \"materials/{plane_data['texture'].upper()}\"") 

            # Basic UVs for VMF. These are simplified and might require manual fine-tuning in Hammer.
            # A common scale for Quake-like textures might be 16 units per texture repeat (1/16 = 0.0625).
            vmf_lines.append("            \"uaxis\" \"[1 0 0 0] 0.0625\"") # X-axis projection, scale 0.0625
            vmf_lines.append("            \"vaxis\" \"[0 1 0 0] 0.0625\"") # Y-axis projection, scale 0.0625
            vmf_lines.append("            \"rotation\" \"0\"")
            vmf_lines.append("            \"lightmapscale\" \"16\"") # Default lightmap scale for lightmap grid
            vmf_lines.append("            \"smoothing_groups\" \"0\"")
            vmf_lines.append("        }") # End side
        
        # Editor block for solid (brush) in VMF
        vmf_lines.append("        \"editor\"")
        vmf_lines.append("        {")
        vmf_lines.append("            \"color\" \"255 0 0\"") # Default brush color in Hammer (Red)
        vmf_lines.append("            \"visgroupshown\" \"1\"") # Brush visible in Hammer
        vmf_lines.append("            \"visgroupautoshown\" \"1\"") # Brush auto-visible
        vmf_lines.append("            \"logicalpos\" \"[0 0]\"") # Add logicalpos for brushes
        vmf_lines.append("        }")
        vmf_lines.append("    }") # End solid

    # Editor block for worldspawn in VMF
    vmf_lines.append("    \"editor\"")
    vmf_lines.append("    {")
    vmf_lines.append("        \"color\" \"255 0 0\"")
    vmf_lines.append("        \"visgroupshown\" \"1\"")
    vmf_lines.append("        \"visgroupautoshown\" \"1\"")
    vmf_lines.append("        \"logicalpos\" \"[0 0]\"")
    vmf_lines.append("    }")
    vmf_lines.append("}") # End world

    # Add a minimal info_player_start entity
    vmf_lines.append("entity")
    vmf_lines.append("{")
    vmf_lines.append(f"    \"id\" \"{current_id}\"")
    current_id += 1
    vmf_lines.append("    \"classname\" \"info_player_start\"")
    vmf_lines.append("    \"origin\" \"0 0 64\"") # Default spawn point
    vmf_lines.append("    \"angles\" \"0 0 0\"") # Default orientation
    vmf_lines.append("    \"editor\"")
    vmf_lines.append("    {")
    vmf_lines.append("        \"color\" \"255 255 0\"") # Yellow for player start
    vmf_lines.append("        \"visgroupshown\" \"1\"")
    vmf_lines.append("        \"visgroupautoshown\" \"1\"")
    vmf_lines.append("        \"logicalpos\" \"[0 0]\"")
    vmf_lines.append("    }")
    vmf_lines.append("}")

    # Add an empty hidden block (often present in VMFs)
    vmf_lines.append("hidden")
    vmf_lines.append("{")
    vmf_lines.append("}")

    return "\n".join(vmf_lines)


def run_resource_compiler(compiler_path, input_vmf_path, console_widget):
    """
    Runs the Half-Life: Alyx resourcecompiler.exe to compile a VMF file into a VMAP.
    """
    try:
        # The resourcecompiler expects the input path to be either absolute or relative
        # to the game's content root. Using absolute path for simplicity and robustness.
        # The '-f' flag forces compilation even if the file is considered up-to-date.
        command = [compiler_path, "-f", input_vmf_path]

        # Set VPROJECT environment variable and current working directory for the subprocess call
        env = os.environ.copy()
        
        compiler_bin_dir = os.path.dirname(compiler_path) # F:\...\game\bin\win64
        # The 'content' folder is the root for user-created content in Alyx addons
        # This path needs to be relative to the SteamLibrary path, not just 'Half-Life Alyx'
        # Let's derive it more robustly:
        # compiler_path: F:\SteamLibrary\steamapps\common\Half-Life Alyx\game\bin\win64\resourcecompiler.exe
        # Step 1: F:\SteamLibrary\steamapps\common\Half-Life Alyx\game\bin\win64
        # Step 2: F:\SteamLibrary\steamapps\common\Half-Life Alyx\game\bin
        # Step 3: F:\SteamLibrary\steamapps\common\Half-Life Alyx\game
        # Step 4: F:\SteamLibrary\steamapps\common\Half-Life Alyx
        # Step 5: F:\SteamLibrary\steamapps\common\Half-Life Alyx\content
        
        alyx_base_dir = os.path.dirname(os.path.dirname(os.path.dirname(compiler_bin_dir)))
        alyx_content_root = os.path.join(alyx_base_dir, "content")

        env['VPROJECT'] = alyx_content_root # Point VPROJECT to the 'content' folder
        
        # CWD remains the compiler's bin directory
        subprocess_cwd = compiler_bin_dir
        
        console_widget.insert(tk.END, f"\n  Attempting to run resourcecompiler with VPROJECT='{env['VPROJECT']}' and CWD='{subprocess_cwd}'\n")
        console_widget.insert(tk.END, f"  Command: {' '.join(command)}\n")
        console_widget.see(tk.END)

        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding='utf-8', errors='replace', env=env, cwd=subprocess_cwd)
        
        # Read stdout and stderr line by line to update the console in real-time
        for line in iter(process.stdout.readline, ''):
            console_widget.insert(tk.END, line)
            console_widget.see(tk.END)
            console_widget.update_idletasks()
        for line in iter(process.stderr.readline, ''):
            console_widget.insert(tk.END, f"[RC_ERROR] {line}") # Prefix stderr for clarity
            console_widget.see(tk.END)
            console_widget.update_idletasks()

        process.wait() # Wait for the process to complete

        if process.returncode != 0:
            console_widget.insert(tk.END, f"[ERROR] resourcecompiler exited with code {process.returncode}\n")
            return False
        else:
            console_widget.insert(tk.END, "resourcecompiler finished successfully.\n")
            return True
    except FileNotFoundError:
        console_widget.insert(tk.END, f"[ERROR] resourcecompiler.exe not found at '{compiler_path}'. Please check the path.\n")
        return False
    except subprocess.CalledProcessError as e:
        console_widget.insert(tk.END, f"[ERROR] resourcecompiler command failed: {e}\n")
        console_widget.insert(tk.END, f"Stdout: {e.stdout}\nStderr: {e.stderr}\n")
        return False
    except Exception as e:
        console_widget.insert(tk.END, f"[ERROR] An unexpected error occurred while running resourcecompiler: {e}\n")
        return False


def convert_folder(input_folder, output_base_folder, resource_compiler_path, console_widget):
    """
    Orchestrates the conversion process:
    1. Parses Quake .map files.
    2. Generates Source 1 .vmf files (using original texture names).
    3. Uses resourcecompiler.exe to compile .vmf to .vmap.
    Output messages are redirected to the provided console_widget.
    """
    def print_to_console(s):
        """Helper function to print messages to the GUI console and auto-scroll."""
        console_widget.insert(tk.END, s + "\n")
        console_widget.see(tk.END) # Auto-scroll to the end
        console_widget.update_idletasks() # Force GUI update

    if not os.path.exists(input_folder):
        print_to_console(f"Error: Quake Maps Input folder '{input_folder}' does not exist. Please check the path.")
        return

    if not os.path.exists(resource_compiler_path):
        print_to_console(f"Error: resourcecompiler.exe not found at '{resource_compiler_path}'. Please check the path.")
        return

    # Define the addon content structure: [output_base_folder]/quakeautomatedscriptport/[maps|materials]
    # Note: 'materials' folder is still created for consistency, but no custom materials are generated by this script.
    addon_content_dir = os.path.join(output_base_folder, "quakeautomatedscriptport")
    maps_output_dir = os.path.join(addon_content_dir, "maps")
    materials_output_dir = os.path.join(addon_content_dir, "materials") 

    # Create all necessary output directories, including the addon folder itself
    os.makedirs(addon_content_dir, exist_ok=True)
    os.makedirs(maps_output_dir, exist_ok=True)
    os.makedirs(materials_output_dir, exist_ok=True) # Create materials dir, but it will be empty by this script

    map_files_found = False

    print_to_console(f"\n--- Starting Map Conversion Process ---")
    print_to_console(f"Scanning input folder: '{input_folder}' for .map files...")
    map_files_to_process = []
    # Walk through the input folder to find all .map files
    for root, dirs, files in os.walk(input_folder):
        for file in files:
            if file.lower().endswith(".map"):
                map_files_to_process.append(os.path.join(root, file))

    if not map_files_to_process:
        print_to_console(f"No .map files found in '{input_folder}' or its subdirectories. Nothing to convert.")
        return

    print_to_console(f"Found {len(map_files_to_process)} .map files to convert:")
    for map_filepath in map_files_to_process:
        print_to_console(f"- {map_filepath}")
        map_files_found = True
        map_name = os.path.splitext(os.path.basename(map_filepath))[0]
        # Construct the .vmf file path within the 'maps' subdirectory
        vmf_filepath = os.path.join(maps_output_dir, f"{map_name}.vmf")

        print_to_console(f"\nProcessing Quake map: {map_filepath}...")
        # brushes now contains 'plane' and 'texture' data
        brushes = parse_quake_map(map_filepath) 

        if brushes:
            vmf_content = generate_vmf_content(brushes)
            try:
                with open(vmf_filepath, 'w') as f:
                    f.write(vmf_content)
                print_to_console(f"Generated Source 1 .vmf file: {vmf_filepath}")
                
                # --- Run resourcecompiler on the generated VMF ---
                print_to_console(f"Attempting to compile {map_name}.vmf using resourcecompiler...")
                if run_resource_compiler(resource_compiler_path, vmf_filepath, console_widget):
                    print_to_console(f"Successfully compiled {map_name}.vmf to .vmap_c.")
                else:
                    print_to_console(f"[ERROR] Failed to compile {map_name}.vmf. Please review resourcecompiler output above for details.")

            except IOError as e:
                print_to_console(f"[ERROR] Could not write .vmf file '{vmf_filepath}': {e}")
            except Exception as e:
                print_to_console(f"[ERROR] An unexpected error occurred during VMF generation or compilation for {map_name}.vmf: {e}")
        else:
            print_to_console(f"No brushes found in {map_filepath}. Skipping .vmf generation and compilation.")

    if not map_files_found:
        print_to_console(f"No .map files were processed. Please ensure your input folder contains .map files.")
        return

    print_to_console("\n--- Conversion process completed. ---")
    print_to_console(f"Output files are located in: {addon_content_dir}")
    print_to_console("\nIMPORTANT NOTES FOR HALF-LIFE: ALYX:")
    print_to_console(f"1. Copy the entire '{os.path.basename(addon_content_dir)}' folder (located at '{addon_content_dir}')")
    print_to_console("   into your Half-Life: Alyx addon's 'content' directory.")
    print_to_console("   Example: `Half-Life Alyx/game/hlvr_addons/my_addon_name/content/`")
    print_to_console("2. This script provides a simplified conversion of Quake map geometry. Complex geometry (e.g., curved surfaces, precise UVs, advanced entities) are not fully handled.")
    print_to_console("3. Quake uses a Z-up coordinate system, while Source 2 typically uses Y-up. The script attempts to convert (X,Y,Z) to (X,Z,-Y). You might still need to adjust the map's orientation in Hammer after import.")
    print_to_console("4. **Material Assignment:** The generated VMFs will now include the original Quake texture names (e.g., 'WALL_TEX'). You will need to manually create corresponding Source 2 materials (`.vmat` files) in Hammer and apply them to the brushes. The `materials/` folder in the output will be empty by this script.")
    print_to_console("5. The resourcecompiler.exe has converted the generated .vmf files to .vmap_c.")
    print_to_console("6. For best results, you may need to manually adjust materials, brush geometry, and add entities in Half-Life: Alyx's Hammer editor.")


class QuakeVmapConverterApp:
    def __init__(self, master):
        self.master = master
        master.title("Quake .map to Alyx .vmap Converter")

        # Define dark theme colors for a modern look
        self.bg_dark_gray = "#2B2B2B"
        self.fg_light_gray = "#E0E0E0"
        self.button_bg = "#4A4A4A"
        self.button_fg = "#FFFFFF"
        self.console_bg = "#1E1E1E"
        self.console_text_color = "#BB86FC" # A shade of purple for console output

        master.config(bg=self.bg_dark_gray)

        # Use tk.StringVar for dynamic path updates in Entry widgets
        script_dir = os.path.dirname(__file__)
        self.input_folder_var = tk.StringVar(value=os.path.normpath(os.path.join(script_dir, "quake_maps_input")))
        # Set the main output base folder to a generic 'alyx_output' in the script's directory.
        # The 'quakeautomatedscriptport' folder will be created inside this.
        self.output_folder_var = tk.StringVar(value=os.path.normpath(os.path.join(script_dir, "alyx_output")))
        # New variable for resourcecompiler.exe path, pre-filled with the user-provided path
        self.resource_compiler_path_var = tk.StringVar(value=os.path.normpath(r"F:\SteamLibrary\steamapps\common\Half-Life Alyx\game\bin\win64\resourcecompiler.exe"))


        self.create_widgets()
        self.setup_dummy_files() # Setup dummy files on app start for convenience

    def create_widgets(self):
        # Input Folder Selection
        tk.Label(self.master, text="Quake Maps Input Folder:", bg=self.bg_dark_gray, fg=self.fg_light_gray).pack(pady=(10, 0))
        input_frame = tk.Frame(self.master, bg=self.bg_dark_gray)
        input_frame.pack(fill=tk.X, padx=10)
        tk.Entry(input_frame, textvariable=self.input_folder_var, width=50, bg=self.button_bg, fg=self.button_fg, insertbackground=self.fg_light_gray).pack(side=tk.LEFT, fill=tk.X, expand=True)
        tk.Button(input_frame, text="Browse", command=lambda: self.browse_folder(self.input_folder_var), bg=self.button_bg, fg=self.button_fg, activebackground=self.fg_light_gray, activeforeground=self.button_bg).pack(side=tk.RIGHT)

        # Output Folder Selection
        tk.Label(self.master, text="Alyx Addon Content Base Folder (e.g., alyx_output):", bg=self.bg_dark_gray, fg=self.fg_light_gray).pack(pady=(10, 0))
        output_frame = tk.Frame(self.master, bg=self.bg_dark_gray)
        output_frame.pack(fill=tk.X, padx=10)
        tk.Entry(output_frame, textvariable=self.output_folder_var, width=50, bg=self.button_bg, fg=self.button_fg, insertbackground=self.fg_light_gray).pack(side=tk.LEFT, fill=tk.X, expand=True)
        tk.Button(output_frame, text="Browse", command=lambda: self.browse_folder(self.output_folder_var), bg=self.button_bg, fg=self.button_fg, activebackground=self.fg_light_gray, activeforeground=self.button_bg).pack(side=tk.RIGHT)

        # ResourceCompiler.exe Path Selection
        tk.Label(self.master, text="resourcecompiler.exe Path:", bg=self.bg_dark_gray, fg=self.fg_light_gray).pack(pady=(10, 0))
        compiler_frame = tk.Frame(self.master, bg=self.bg_dark_gray)
        compiler_frame.pack(fill=tk.X, padx=10)
        tk.Entry(compiler_frame, textvariable=self.resource_compiler_path_var, width=50, bg=self.button_bg, fg=self.button_fg, insertbackground=self.fg_light_gray).pack(side=tk.LEFT, fill=tk.X, expand=True)
        tk.Button(compiler_frame, text="Browse", command=lambda: self.browse_file(self.resource_compiler_path_var), bg=self.button_bg, fg=self.button_fg, activebackground=self.fg_light_gray, activeforeground=self.button_bg).pack(side=tk.RIGHT)


        # Frame for buttons
        button_frame = tk.Frame(self.master, bg=self.bg_dark_gray)
        button_frame.pack(pady=10)

        self.compile_button = tk.Button(button_frame, text="Compile Maps", command=self.start_conversion_thread, bg=self.button_bg, fg=self.button_fg, activebackground=self.fg_light_gray, activeforeground=self.button_bg)
        self.compile_button.pack(side=tk.LEFT, padx=5)

        self.clear_button = tk.Button(button_frame, text="Clear Console", command=self.clear_console, bg=self.button_bg, fg=self.button_fg, activebackground=self.fg_light_gray, activeforeground=self.button_bg)
        self.clear_button.pack(side=tk.LEFT, padx=5)

        # Console output area
        self.console_text = scrolledtext.ScrolledText(self.master, wrap=tk.WORD, height=25, width=80, state='disabled', bg=self.console_bg, fg=self.console_text_color, insertbackground=self.fg_light_gray)
        self.console_text.pack(padx=10, pady=10, fill=tk.BOTH, expand=True)
        # Apply tag for console text color (though fg already sets it, this is for consistency/future tags)
        self.console_text.tag_config("console_output", foreground=self.console_text_color)


        # Redirect stdout to the console_text widget
        self.text_redirector = TextRedirector(self.console_text)
        sys.stdout = self.text_redirector
        sys.stderr = self.text_redirector # Also redirect stderr

    def browse_folder(self, path_var):
        """Opens a file dialog to select a folder and updates the StringVar."""
        folder_selected = filedialog.askdirectory()
        if folder_selected:
            path_var.set(os.path.normpath(folder_selected))

    def browse_file(self, path_var):
        """Opens a file dialog to select a file and updates the StringVar."""
        file_selected = filedialog.askopenfilename(filetypes=[("Executable files", "*.exe")])
        if file_selected:
            path_var.set(os.path.normpath(file_selected))

    def clear_console(self):
        """Clears the text in the console output area."""
        self.console_text.config(state='normal')
        self.console_text.delete(1.0, tk.END)
        self.console_text.config(state='disabled')

    def start_conversion_thread(self):
        """Starts the conversion process in a separate thread to keep the GUI responsive."""
        self.clear_console()
        self.compile_button.config(state='disabled') # Disable buttons during conversion
        self.clear_button.config(state='disabled')

        # Get current paths from entry widgets
        input_folder = self.input_folder_var.get()
        output_base_folder = self.output_folder_var.get()
        resource_compiler_path = self.resource_compiler_path_var.get()

        # Run conversion in a separate thread
        self.conversion_thread = threading.Thread(target=self.run_conversion, args=(input_folder, output_base_folder, resource_compiler_path))
        self.conversion_thread.start()
        # Start checking thread status periodically to re-enable buttons
        self.master.after(100, self.check_conversion_thread) 

    def run_conversion(self, input_folder, output_base_folder, resource_compiler_path):
        """Executes the map conversion logic."""
        try:
            convert_folder(input_folder, output_base_folder, resource_compiler_path, self.console_text)
            messagebox.showinfo("Conversion Complete", "Map conversion process finished successfully!")
        except Exception as e:
            messagebox.showerror("Conversion Error", f"An unexpected error occurred during conversion: {e}")
            print(f"[ERROR] Critical error during conversion: {e}")
        finally:
            # Re-enable buttons in the main thread after conversion finishes
            self.master.after(0, self.enable_buttons)

    def check_conversion_thread(self):
        """Checks if the conversion thread is still alive and re-enables buttons when it finishes."""
        if self.conversion_thread.is_alive():
            self.master.after(100, self.check_conversion_thread) # Keep checking
        else:
            self.enable_buttons()

    def enable_buttons(self):
        """Re-enables the GUI buttons."""
        self.compile_button.config(state='normal')
        self.clear_button.config(state='normal')

    def setup_dummy_files(self):
        """
        Ensures input folder and dummy map exist for testing/initial setup.
        """
        # Ensure base directories exist
        os.makedirs(self.input_folder_var.get(), exist_ok=True)

        # Create sample map only if the input folder is empty
        sample_map_path = os.path.join(self.input_folder_var.get(), "sample_map.map")
        if not os.listdir(self.input_folder_var.get()): # Check if folder is empty
            sample_map_content = """
// My Sample Quake Map
{
    "classname" "worldspawn"
    {
        ( -128 -128 0 ) ( 128 -128 0 ) ( -128 128 0 ) WALL_TEX [ 1 0 0 0 ] [ 0 1 0 0 ] 0 1 1
        ( -128 -128 128 ) ( -128 128 128 ) ( 128 -128 128 ) CEILING_TEX [ 1 0 0 0 ] [ 0 1 0 0 ] 0 1 1
        ( -128 -128 0 ) ( -128 -128 128 ) ( -128 128 0 ) FLOOR_TEX [ 1 0 0 0 ] [ 0 1 0 0 ] 0 1 1
        ( 128 -128 0 ) ( 128 128 0 ) ( 128 -128 128 ) BRICK_TEX [ 1 0 0 0 ] [ 0 1 0 0 ] 0 1 1
        ( -128 128 0 ) ( 128 128 0 ) ( -128 128 128 ) {CLIP [ 1 0 0 0 ] [ 0 1 0 0 ] 0 1 1
        ( -128 -128 0 ) ( -128 128 0 ) ( 128 -128 0 ) WATER_TEX [ 1 0 0 0 ] [ 0 1 0 0 ] 0 1 1
    }
    {
        "classname" "light"
        "origin" "0 0 64"
        "light" "300"
    }
}
"""
            with open(sample_map_path, "w") as f:
                f.write(sample_map_content)
            print(f"Created a sample map file: {sample_map_path}")
        else:
            print(f"Input folder '{self.input_folder_var.get()}' is not empty. Skipping sample map creation.")


class TextRedirector:
    """A class to redirect stdout and stderr to a Tkinter Text widget."""
    def __init__(self, widget):
        self.widget = widget

    def write(self, s):
        # Schedule the update on the main Tkinter thread to prevent threading issues with Tkinter
        self.widget.after(0, self._write_to_widget, s)

    def _write_to_widget(self, s):
        """Internal method to safely write text to the Tkinter Text widget."""
        self.widget.config(state='normal') # Enable editing
        self.widget.insert(tk.END, s, "console_output") # Apply tag for color
        self.widget.see(tk.END) # Auto-scroll to the end
        self.widget.config(state='disabled') # Disable editing
        self.widget.update_idletasks() # Force GUI update immediately

    def flush(self):
        """Required for file-like object compatibility."""
        pass 


if __name__ == "__main__":
    root = tk.Tk()
    app = QuakeVmapConverterApp(root)
    root.mainloop()
