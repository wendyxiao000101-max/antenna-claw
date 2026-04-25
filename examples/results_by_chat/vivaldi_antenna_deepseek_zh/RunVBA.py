import cst
import cst.interface
import os

# Define CST project path
project_path = os.path.join(os.getcwd(), "Antenna_With_Materials.cst")

# Open CST project
cst_new_project = cst.interface.DesignEnvironment().open_project(project_path)

# Read FullVBA.bas (contains all macros)
with open('FullVBA.bas', 'r', encoding='utf8') as file:
    bas_script = file.read()

# Run the VBA macro inside CST
cst_new_project.modeler.add_to_history('Execute FullVBA', bas_script)

# Save the modified project
save_path = os.path.join(os.getcwd(), "Antenna.cst")
cst_new_project.save(save_path)

# Close CST project
cst_new_project.close()

print("FullVBA.bas executed and Antenna.cst saved successfully.")
