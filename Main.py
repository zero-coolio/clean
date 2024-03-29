import os
from pprint import pprint


def main():
    pprint("Hello World! !")
    current_working_directory = os.getcwd()
    current_working_directory
    pprint(current_working_directory)


if __name__ == "__main__":
    main()
