import os

from ui_apps.dev_app import main


if __name__ == "__main__":
    print("RUNNING FILE =", __file__)
    print("CWD =", os.getcwd())
    main()
