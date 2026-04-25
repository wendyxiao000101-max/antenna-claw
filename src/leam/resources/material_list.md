# Material List (CST)

This project does not ship CST material library data. Material names are enumerated at runtime from your local CST installation.

How it works:
- Set the CST install path in config.json as "cst_path" or export CST_PATH.
- LEAM reads <CST_PATH>\Library\Materials and uses only files ending in .mtd.
- Non-.mtd entries (e.g., filelist.txt or material library.mal) are ignored.

If cst_path is not configured or the folder is missing, material extraction returns an empty list.
