import re, yaml, os, json


def parse_basic_config(config_file):
    """
    Configures custom yaml loading behavior and parses config file
    """

    env_pattern = re.compile(r"\$\{(.*?)\}(.*)", re.VERBOSE)
    def env_var_constructor(loader, node):
        """
        Converts ${VAR}/* from config file to 'os.environ[VAR] + *'
        Modified from: https://www.programcreek.com/python/example/61563/yaml.add_implicit_resolver
        """
        value = loader.construct_scalar(node)
        env_var, remainder = env_pattern.match(value).groups()
        if env_var not in os.environ:
            raise ValueError("config requires envirnonment variable {} which is not set".format(env_var))
        return os.environ[env_var] + remainder
    yaml.add_implicit_resolver("!env", env_pattern, Loader=yaml.SafeLoader)
    yaml.add_constructor('!env', env_var_constructor, Loader=yaml.SafeLoader)

    with open(os.path.expanduser(config_file), 'r') as config:
        return yaml.load(config, Loader=yaml.SafeLoader)
