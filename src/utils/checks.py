def check_role(role_identifier):
    # Assume this function is part of a larger codebase that checks the role
    if isinstance(role_identifier, int):
        # logic to resolve role by id
        pass  # replace with actual implementation
    elif isinstance(role_identifier, str):
        # logic to resolve role by name
        pass  # replace with actual implementation
    else:
        raise ValueError("Role identifier must be an int or str.")


# Function to raise MAINTENANCE_ACTIVE
def raise_maintenance_active():
    raise Exception('Maintenance mode is active.')
    
# Example usage:
# raise_maintenance_active()
# check_role(1)
# check_role('admin')
