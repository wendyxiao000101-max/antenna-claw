try:
    from .config import ensure_openai_api_key, get_paths
except ImportError:  # Fallback when executed as a script.
    from leam.config import ensure_openai_api_key, get_paths



def main() -> int:
    print("Welcome to the LEAM package.")
    try:
        ensure_openai_api_key()
        cst_path, material_library_path, python_libs = get_paths()
    except (RuntimeError, ValueError, FileNotFoundError) as exc:
        print(str(exc))
        return 1

    print(f"Material Library Path: {material_library_path}")
    print(f"CST Path: {cst_path}")
    print(f"Python Libraries Path: {python_libs}")
    return 0



if __name__ == "__main__":
    raise SystemExit(main())
