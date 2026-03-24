#!/bin/bash

# Get username from PAM
USERNAME="$PAM_USER"

# Ensure the variable is not empty
if [[ -z "$USERNAME" ]]; then
    exit 1
fi

if [[ "$USERNAME" == "root" ]]; then
    exit 0
fi


# Default home directory
HOME_DIR="/bigdata/userhome"

# Extract user type from the username format "md5_<type><hash>"
if [[ "$USERNAME" =~ ^md5_t ]]; then
    GROUP="teachers"
    HOME_DIR="$HOME_DIR/teachers"
elif [[ "$USERNAME" =~ ^md5_s ]]; then
    GROUP="students"
    HOME_DIR="$HOME_DIR/students"
elif [[ "$USERNAME" =~ ^md5_u ]]; then
    GROUP="undefined"
    HOME_DIR="$HOME_DIR/undefined"
else
    # If the format is unrecognized, exit to avoid incorrect user creation
    echo "Unknown username format for user $USERNAME" >> /var/log/xrdp-user-creation.log
    exit 1
fi

# Check if user exists
if ! id "$USERNAME" &>/dev/null; then
    # Create user with the specified home directory and group
    useradd -m -s /bin/bash -d "$HOME_DIR/$USERNAME" -g "$GROUP" "$USERNAME"

#    # Set default password (hashed version for security)
#    echo "$USERNAME:test" | chpasswd

    # Log user creation
    echo "$(date) - Created user $USERNAME with home $HOME_DIR/$USERNAME in group $GROUP" >> /var/log/xrdp-user-creation.log
fi

exit 0
