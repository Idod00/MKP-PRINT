#!/bin/bash

# Change current directory to where this script resides
SCRIPTPATH=$(cd ${0%/*} && echo $PWD/${0##*/})
SCRIPTDIR=`dirname "$SCRIPTPATH"`
cd $SCRIPTDIR

# Set up temporary dir path
TEMPDIR="/tmp/package-sh-$$"

# Set up package name (based on package name and version no in configure.ac)
NAME=`head -1 configure.ac | cut -f2 --delimiter='[' | cut -f1 --delimiter=']'`
VER=`head -1 configure.ac | cut -f3 --delimiter='[' | cut -f1 --delimiter=']'`
PACKAGENAME="${NAME}-${VER}"

# Create temp dirs
mkdir -p ${TEMPDIR}
mkdir -p ${TEMPDIR}/${PACKAGENAME}

# Generate VERSION file
echo "Honeywell CUPS Driver v${VER} build"  > VERSION
echo ""                                          >> VERSION
echo "${PACKAGENAME}"                            >> VERSION

# Generate PPD files
cd src
ppdc -d ppd generic-dp_intermec.drv
ppdc -d ppd generic-dp_honeywell.drv
ppdc -d ppd generic-dp_honeywell_px940.drv
ppdc -d ppd generic-dpl_honeywell.drv
cd ..

# Copy files to be packaged to temp dir
cp -r * ${TEMPDIR}/${PACKAGENAME}/

# Package into tar-ball
cd ${TEMPDIR}
tar --exclude='.svn' -czvf ${TEMPDIR}/${PACKAGENAME}.tar.gz ${PACKAGENAME} \
  > /dev/null
cd - > /dev/null

# Clean up PPD files
rm src/ppdintermec/*
rm src/ppdhoneywell/*

# Clean up VERSION file
rm VERSION

# Copy package back to original dir
cp ${TEMPDIR}/${PACKAGENAME}.tar.gz .

# Delete temporary files
rm -rf ${TEMPDIR}

# Notify user
echo "Done!"

exit 0;
